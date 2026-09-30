"""Multiple acceptable services: explicit scoring, public-cost exact baselines."""
import argparse
import itertools
import json
from copy import deepcopy
from time import perf_counter_ns
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_structural_generalization import TaskSpec, make_episode_from_specs
from probe_c3_parallel_model_pilot import sample_parallel
from probe_c3_staggered_release import release_order_records
from probe_c3_release_state_20260930 import metrics
from runtime.scheduling_oracle import ideal_schedule
from runtime.event_simulator import run_event_simulation
from runtime.protocol import assert_agent_decision
from runtime.replay_client import MemoryReplayClient
from runtime.tool_contract import validate_tool_call
from runtime.episode_validation import validate_event_episode
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from evaluate import task_accepts_action
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_c3_multimode'
OFFLINE = ROOT / 'results' / 'c3_multimode_offline_20260930.json'
LIVE = ROOT / 'results' / 'c3_multimode_model_20260930.json'
LOGDIR = ROOT / 'runs' / 'c3-multimode-20260930'
LABELS = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator',
          'FixedProposalExact', 'ReleasedModeEnumerationExact')
CAPACITIES = (3, 4, 5)
PUBLIC_IDS = {3: 'HC-E2-L14', 4: 'HC-E2-B23', 5: 'HC-E2-K58'}

def build(capacity):
    specs = (TaskSpec('laundry', 'LaundryAgent', 'washer', 'eco', 1, 8, 10, 80),
             TaskSpec('water', 'WaterAgent', 'water_heater', 'prepare', 2, 5, 6, 100),
             TaskSpec('meal', 'MealAgent', 'cooktop', 'prepare', 1, 5, 11, 70))
    episode = make_episode_from_specs('multimode', specs, 1)
    episode['episode_id'] = episode['base_episode_id'] = PUBLIC_IDS[capacity]
    episode['home']['resources']['max_power_kw'] = capacity
    episode['home']['resources']['task_power_bounds_kw']['laundry'] = 2
    episode['conflict_rules'][0]['capacity'] = capacity
    episode['source_type'] = 'controlled_multimode_service_contract'
    episode['resource_unit'] = 'abstract_admission_unit'
    episode.pop('resource_pressure', None)
    episode['scenario_assumptions'] = {'resource_semantics': 'abstract constant admission units, not measured kW',
                                     'legacy_field_mapping': 'power_kw/max_power_kw store abstract units for this opt-in pilot',
                                     'mode_authority': 'fixed proposal methods cannot change operation; mode enumeration may choose any publicly declared acceptable service',
                                     'physical_calibration': 'none', 'future_information': 'all tasks released at zero'}
    for task in episode['task_stream']:
        task['requested_service'] = 'ordinary_cleaned' if task['task_id'] == 'laundry' else 'completed'
        task['acceptable_actions'] = [task.pop('required_action')]
        task['goal'] = (('Clean ordinary laundry. Both eco and fast cleaning services are acceptable. '
                         if task['task_id'] == 'laundry' else f"Provide the {task['task_id']} service. ")
                        + 'Do not miss any task deadline; among feasible household plans, prefer earlier completion of all requests. '
                        + 'Use the current public coordination_context. Propose only your own device action.')
    laundry = episode['task_stream'][0]
    laundry['acceptable_actions'].append({'target': 'washer', 'operation': 'fast'})
    fast_ground = deepcopy(episode['action_grounding'][0])
    fast_ground.update({'operation': 'fast', 'grounded_operation': 'fast', 'duration_ms': 240000, 'power_kw': 2})
    episode['action_grounding'].append(fast_ground)
    fast_tool = deepcopy(episode['tool_catalog'][0])
    fast_tool.update({'operation': 'fast', 'tool_name': 'washer_fast'})
    episode['tool_catalog'].append(fast_tool)
    for task in episode['task_stream']:
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        target = task['action_template']['target']
        tools = [t for t in episode['tool_catalog'] if t['agent_id'] == agent['agent_id']]
        for tool in tools:
            ground = next(g for g in episode['action_grounding'] if g['agent_id'] == agent['agent_id'] and g['operation'] == tool['operation'])
            tool['provides_service'] = task['requested_service']
            tool['cost_contract'] = {'duration_ms': ground['duration_ms'], 'resource_units': ground['power_kw']}
            tool['description'] = (f"Provide {task['requested_service']} using {tool['operation']}. "
                                   f"Declared cost: {ground['duration_ms']} ms and {ground['power_kw']} abstract admission units. "
                                   'This is a synthetic service contract, not calibrated device physics.')
        off = {'agent_id': agent['agent_id'], 'tool_name': target + '_off', 'target': target, 'operation': 'off',
               'parameters': [], 'preconditions': deepcopy(tools[0]['preconditions']), 'provides_service': 'none',
               'cost_contract': {'duration_ms': 100, 'resource_units': 0}, 'description': 'Leave idle; supplies no requested service.'}
        episode['tool_catalog'].append(off)
        episode['action_grounding'].append({'agent_id': agent['agent_id'], 'task_id': task['task_id'], 'target': target,
                                            'operation': 'off', 'grounded_operation': 'off', 'duration_ms': 100, 'power_kw': 0,
                                            'effects': {f'devices.{target}': 'idle'}, 'completion_effects': {f'devices.{target}': 'idle'}})
        agent['tools'] = [t['tool_name'] for t in tools] + [off['tool_name']]
        agent['observable_state'].append('coordination_context')
    episode['initial_state']['values']['coordination_context'] = {
        'resource_capacity_units': capacity, 'all_tasks_released': True,
        'objective': 'all services and deadlines first; then earliest whole-house completion',
        'requests': [{'task_id': t['task_id'], 'deadline_ms': t['completion_deadline_ms'], 'requested_service': t['requested_service'],
                      'modes': [{'operation': tool['operation'], **tool['cost_contract']} for tool in episode['tool_catalog']
                                if tool['agent_id'] == t['agent_id'] and tool['provides_service'] == t['requested_service']]}
                     for t in episode['task_stream']]}
    return episode

class PublicModeClient:
    include_evaluation_hints = False
    def __init__(self, mode, latencies):
        self.mode, self.latencies = mode, latencies
    def decide(self, request, instructions=''):
        task = request['task']
        candidates = [t for t in request['available_actions'] if t['provides_service'] == task['requested_service']]
        tool = next((t for t in candidates if t['operation'] == self.mode), candidates[0])
        self.last_latency_ms = self.latencies[task['task_id']]
        decision = {'response_type': 'action_proposal', 'actions': [{
            'proposal_id': request['request_id'] + ':public', 'target': tool['target'], 'operation': tool['operation'],
            'parameters': [], 'based_on_state_version': request['state_version'],
            'requires': [{**r, 'range_min': None, 'range_max': None} for r in tool['preconditions']],
            'estimated_duration_ms': tool['cost_contract']['duration_ms'],
            'estimated_power_kw': tool['cost_contract']['resource_units']}],
            'accepted_proposal_ids': [], 'rejected_proposal_ids': [], 'defer_until_ms': None, 'reason_code': 'goal_progress'}
        assert_agent_decision(decision)
        return decision

def records_for(episode, mode, latencies):
    from runtime.protocol import build_agent_request
    provider = PublicModeClient(mode, latencies)
    records = {}
    for task in episode['task_stream']:
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        request = build_agent_request(episode, agent, task, architecture='IndependentMultiAgent', current_time_ms=0)
        records[task['task_id']] = {'request': request, 'decision': provider.decide(request), 'logical_latency_ms': latencies[task['task_id']]}
    return records

def public_plan(episode, records, can_change_modes):
    """All tasks released, all proposals returned; public costs only, exact makespan."""
    if any(t['release_at_ms'] != 0 for t in episode['task_stream']):
        raise ValueError('this baseline is restricted to all-released batches')
    ready = max(r['logical_latency_ms'] for r in records.values())
    now = ready + episode['simulation']['command_latency_ms']
    choices = []
    for task in episode['task_stream']:
        tools = [t for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id']
                 and t['tool_name'] in next(a['tools'] for a in episode['agents'] if a['agent_id'] == task['agent_id'])
                 and t['provides_service'] == task['requested_service']]
        if not can_change_modes:
            actions = records[task['task_id']]['decision']['actions']
            tools = [t for t in tools if len(actions) == 1 and t['operation'] == actions[0]['operation'] and t['target'] == actions[0]['target']]
        if not tools:
            return None
        choices.append(tools)
    best = None
    for selected in itertools.product(*choices):
        changed = deepcopy(episode)
        for task, tool in zip(changed['task_stream'], selected):
            task['action_template'].update({'operation': tool['operation'], 'duration_ms': tool['cost_contract']['duration_ms'],
                                            'power_kw': tool['cost_contract']['resource_units']})
        if ideal_schedule(changed, now_ms=now) is None:
            continue
        low = now + max(t['action_template']['duration_ms'] for t in changed['task_stream'])
        high = max(t['completion_deadline_ms'] for t in changed['task_stream'])
        while low < high:
            mid = (low + high) // 2
            trial = deepcopy(changed)
            for task in trial['task_stream']:
                task['completion_deadline_ms'] = min(task['completion_deadline_ms'], mid)
            if ideal_schedule(trial, now_ms=now) is None:
                low = mid + 1
            else:
                high = mid
        for task in changed['task_stream']:
            task['completion_deadline_ms'] = min(task['completion_deadline_ms'], low)
        schedule = ideal_schedule(changed, now_ms=now)
        candidate = {'available_at_ms': ready, 'makespan_ms': low,
                     'tasks': {s['task_id']: {**s, 'operation': tool['operation']} for s, tool in
                               ((s, next(tool for task, tool in zip(episode['task_stream'], selected) if task['task_id'] == s['task_id'])) for s in schedule)}}
        if best is None or candidate['makespan_ms'] < best['makespan_ms']:
            best = candidate
    return best

def run_one(episode, records, label):
    changed, chosen = deepcopy(episode), deepcopy(records)
    start = perf_counter_ns()
    plan = public_plan(episode, records, label == 'ReleasedModeEnumerationExact') if label in LABELS[-2:] else None
    planner_wall_ms = (perf_counter_ns() - start) / 1e6 if label in LABELS[-2:] else None
    if plan:
        for task in changed['task_stream']:
            action = chosen[task['task_id']]['decision']['actions'][0]
            tool = next(t for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id'] and t['operation'] == plan['tasks'][task['task_id']]['operation'])
            if label == 'ReleasedModeEnumerationExact':
                action.update({'operation': tool['operation'], 'target': tool['target'],
                               'estimated_duration_ms': tool['cost_contract']['duration_ms'],
                               'estimated_power_kw': tool['cost_contract']['resource_units']})
        changed['simulation']['released_batch_plan'] = plan
        changed['simulation']['hold_until_ms'] = plan['available_at_ms']
    policy = 'FixedHoldCoordinator' if plan else ('DeadlineAwareCoordinator' if label in LABELS[-2:] else label)
    client = MemoryReplayClient(deepcopy(release_order_records(changed, chosen)))
    trace, result = run_event_simulation(changed, client, policy, 'multimode public-cost baseline', shared_safety_gate=True)
    client.assert_consumed()
    if plan:
        actual = {e['task_id']: e['timestamp_ms'] for e in trace['events'] if e['type'] == 'action_started'}
        if actual != {task_id: p['start_ms'] for task_id, p in plan['tasks'].items()} or not result['all_deadlines_met']:
            raise ValueError('runtime did not execute feasible batch plan')
    starts = [e for e in trace['events'] if e['type'] == 'action_started']
    completes = [e for e in trace['events'] if e['type'] == 'action_completed']
    return {'capacity_units': episode['home']['resources']['max_power_kw'], 'policy': label,
            'mode_authority': 'may_choose_acceptable_mode' if label == 'ReleasedModeEnumerationExact' else 'fixed_proposal',
            'chosen_laundry_mode': next((e['operation'] for e in starts if e['task_id'] == 'laundry'), None),
            'chosen_modes': {e['task_id']: e['operation'] for e in starts},
            **metrics(result), 'task_completion_latency_ms': result['task_completion_latency_ms'],
            'last_actual_completion_ms': max((e['timestamp_ms'] for e in completes), default=None),
            'process_violation_ms': result['state_constraint_violation_duration_ms'],
            'planner_wall_ms': planner_wall_ms, 'plan': plan,
            'actual_proposal_latencies_ms': {t: r['logical_latency_ms'] for t, r in records.items()}}

def prepare():
    hashes = {}
    for cap in CAPACITIES:
        path = DIR / f'capacity-{cap}.json'
        write(path, build(cap))
        hashes[path.name] = digest(path)
    design = {'version': 'multimode-runtime-0.1', 'candidate_sha256': hashes,
              'capacities': list(CAPACITIES), 'scripted_modes': ['eco', 'fast'],
              'arrival_orders': 'all six permutations of three tasks, 800/1000/1200ms',
              'policies': list(LABELS), 'offline_runs': 180,
              'planned_api_requests': 18, 'repetitions': 2, 'max_attempts': 1,
              'mode_authority_groups': 'first four fixed proposal; last can change publicly acceptable mode',
              'objective': 'all services and deadlines, then minimum makespan for exact baselines; waiting separately reported',
              'information': 'all tasks released; same public costs/deadlines/context; exact plans wait all returned proposals',
              'timing': 'plan wall cost separate, not injected; original response times preserved with fixed hold',
              'limits': 'single author-designed structure, synthetic abstract resource units; development not held-out data',
              'status': 'locked_before_multimode_experiments'}
    write(DIR / 'manifest.json', design)
    return design

def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    episodes = {}
    for filename, expected in design['candidate_sha256'].items():
        if digest(DIR / filename) != expected:
            raise ValueError('locked multimode input changed')
        episode = json.loads((DIR / filename).read_text(encoding='utf8'))
        if validate_event_episode(episode):
            raise ValueError('invalid episode')
        episodes[episode['home']['resources']['max_power_kw']] = episode
    return design, episodes

def offline():
    design, episodes = locked()
    rows = []
    for cap, episode in episodes.items():
        for mode in ('eco', 'fast'):
            for order in itertools.permutations(('laundry', 'water', 'meal')):
                records = records_for(episode, mode, {t: 800 + rank * 200 for rank, t in enumerate(order)})
                for label in LABELS:
                    row = run_one(episode, records, label)
                    row.update({'proposed_mode': mode, 'arrival_order': list(order)})
                    rows.append(row)
    if len(rows) != design['offline_runs']:
        raise ValueError('offline grid incomplete')
    result = {'status': 'completed_multimode_scripted_grid', 'new_api_calls': 0,
              'design_sha256': digest(DIR / 'manifest.json'), 'rows': rows}
    write(OFFLINE, result)
    return result

def live():
    design, episodes = locked()
    result = json.loads(LIVE.read_text(encoding='utf8')) if LIVE.exists() else {
        'design_sha256': digest(DIR / 'manifest.json'), 'batches': [], 'status': 'partial'}
    if result['design_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('existing model batch has different design')
    LOGDIR.mkdir(parents=True, exist_ok=True)
    provider = DeepSeekResponsesClient(model='deepseek-flash', max_attempts=1,
                                       logger=EventLogger(LOGDIR / 'model_events.jsonl', 'c3-multimode-20260930'))
    if not provider.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not configured')
    for cap, episode in episodes.items():
        for rep in (1, 2):
            if any(b['capacity_units'] == cap and b['repetition'] == rep for b in result['batches']):
                continue
            sample = sample_parallel(provider, episode, rep + 200)
            scores = []
            for task in episode['task_stream']:
                record = sample['records'].get(task['task_id'])
                actions = record['decision']['actions'] if record else []
                authorized = len(actions) == 1 and validate_tool_call(episode, task['agent_id'], task['task_id'], actions[0]) is None
                scores.append({'task_id': task['task_id'], 'authorized': authorized,
                               'semantic_correct': authorized and task_accepts_action(actions[0], task),
                               'operation': actions[0]['operation'] if actions else None})
            rows = [] if sample['errors'] else [run_one(episode, sample['records'], label) for label in LABELS]
            result['batches'].append({'capacity_units': cap, 'repetition': rep, 'sample': sample, 'scores': scores, 'rows': rows})
            write(LIVE, result)
            print(json.dumps({'capacity': cap, 'rep': rep, 'errors': sample['errors'], 'scores': scores}), flush=True)
    result['status'] = 'complete' if sum(len(b['rows']) for b in result['batches']) == 30 else 'complete_with_errors'
    write(LIVE, result)
    return result

def audit():
    design, episodes = locked()
    scripted = json.loads(OFFLINE.read_text(encoding='utf8'))
    model = json.loads(LIVE.read_text(encoding='utf8'))
    if len(scripted['rows']) != design['offline_runs'] or model['status'] != 'complete':
        raise ValueError('experiment incomplete; report missing batches rather than suppress errors')
    for episode in episodes.values():
        for tool in episode['tool_catalog']:
            ground = next(g for g in episode['action_grounding'] if g['agent_id'] == tool['agent_id'] and g['operation'] == tool['operation'])
            if (tool['cost_contract']['duration_ms'], tool['cost_contract']['resource_units']) != (ground['duration_ms'], ground['power_kw']):
                raise ValueError('public cost contract disagrees with runtime cost')
    mode_pairs = []
    for batch in model['batches']:
        for record in batch['sample']['records'].values():
            if 'acceptable_actions' in record['request']['task'] or 'action_template' in record['request']['task']:
                raise ValueError('scoring hints leaked into model request')
        by_policy = {r['policy']: r for r in batch['rows']}
        fixed, flexible = by_policy['FixedProposalExact'], by_policy['ReleasedModeEnumerationExact']
        for row in (fixed, flexible):
            if not row['plan'] or min(row['task_start_wait_ms'].values()) < row['plan']['available_at_ms'] + 100:
                raise ValueError('exact plan used pending proposals or skipped command latency')
            if row['model_latency_by_task_ms'] != row['actual_proposal_latencies_ms']:
                raise ValueError('actual proposal latency was replaced by batching delay')
        mode_pairs.append({'capacity_units': batch['capacity_units'], 'repetition': batch['repetition'],
                           'proposed_laundry_mode': batch['scores'][0]['operation'],
                           'fixed_plan_mode': fixed['chosen_laundry_mode'], 'enumerated_plan_mode': flexible['chosen_laundry_mode'],
                           'fixed_last_completion_ms': fixed['last_actual_completion_ms'],
                           'enumerated_last_completion_ms': flexible['last_actual_completion_ms'],
                           'whole_plan_completion_improvement_ms': fixed['last_actual_completion_ms'] - flexible['last_actual_completion_ms'],
                           'laundry_wait_change_ms': flexible['task_start_wait_ms']['laundry'] - fixed['task_start_wait_ms']['laundry'],
                           'capability_difference': 'flexible baseline may change mode; fixed baseline may only schedule'})
    summaries = {}
    for kind, rows in (('scripted', scripted['rows']), ('new_model_proposals', [r for b in model['batches'] for r in b['rows']])):
        summaries[kind] = [{'policy': label, 'runs': sum(r['policy'] == label for r in rows),
                            'all_served': sum(r['all_tasks_served'] for r in rows if r['policy'] == label),
                            'all_deadlines': sum(r['all_deadlines_met'] for r in rows if r['policy'] == label)} for label in LABELS]
    logs = [json.loads(line) for line in (LOGDIR / 'model_events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    responses = [e for e in logs if e['event_type'] == 'model_call_completed']
    if len(responses) != 18 or len(mode_pairs) != 6:
        raise ValueError('unexpected fresh batch counts')
    scores = [s for b in model['batches'] for s in b['scores']]
    result = {'status': 'audited_multimode_runtime_pilot',
              'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (LIVE, OFFLINE, DIR / 'manifest.json')},
              'fresh_api_successes': 18, 'semantic_correct': sum(s['semantic_correct'] for s in scores),
              'authorized': sum(s['authorized'] for s in scores), 'model_batches': 6,
              'scripted_runs': 180, 'recorded_policy_runs': 30, 'summaries': summaries, 'mode_pairs': mode_pairs,
              'input_tokens': sum(e.get('input_tokens') or 0 for e in responses),
              'output_tokens': sum(e.get('output_tokens') or 0 for e in responses),
              'limits': design['limits'], 'mode_authority_groups': design['mode_authority_groups']}
    write(ROOT / 'results' / 'c3_multimode_audit_20260930.json', result)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'offline', 'live', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'offline': offline, 'live': live, 'audit': audit}[stage]()
    print(json.dumps({'stage': stage, 'status': result['status'], 'rows': len(result.get('rows', [])), 'batches': len(result.get('batches', []))}))
