"""Preregistered two-mode-task structural replication, synthetic public contracts."""
import argparse
import itertools
import json
from copy import deepcopy
from pathlib import Path
from probe_c3_multimode_20260930 import (build as original_build, PublicModeClient, public_plan,
                                       run_one, LABELS)
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_parallel_model_pilot import sample_parallel
from runtime.protocol import build_agent_request
from runtime.episode_validation import validate_event_episode
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.tool_contract import validate_tool_call
from evaluate import task_accepts_action

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_c3_multimode_replication'
OFFLINE = ROOT / 'results' / 'c3_multimode_replication_offline_20260930.json'
LIVE = ROOT / 'results' / 'c3_multimode_replication_model_20260930.json'
AUDIT = ROOT / 'results' / 'c3_multimode_replication_audit_20260930.json'
LOGDIR = ROOT / 'runs' / 'c3-multimode-replication-20260930'
CAPACITIES = (3, 4, 6)
CONTRACTS = {'laundry': {'eco': (420000, 1), 'fast': (180000, 2)},
             'meal': {'eco': (360000, 1), 'fast': (180000, 2)},
             'water': {'prepare': (240000, 2)}}

def build(capacity):
    episode = original_build(3)
    episode['episode_id'] = episode['base_episode_id'] = f'HC-E2-DUAL-{capacity}'
    episode['home']['resources']['max_power_kw'] = capacity
    episode['conflict_rules'][0]['capacity'] = capacity
    episode['home']['resources']['task_power_bounds_kw']['meal'] = 2
    episode['source_type'] = 'controlled_dual_multimode_service_contract'
    episode['scenario_assumptions']['structure'] = 'two mode-selecting tasks and one tight fixed service'
    meal = next(t for t in episode['task_stream'] if t['task_id'] == 'meal')
    meal['action_template']['operation'] = 'eco'
    meal['acceptable_actions'] = [{'target': 'cooktop', 'operation': op} for op in ('eco', 'fast')]
    meal_ground = next(g for g in episode['action_grounding'] if g['task_id'] == 'meal' and g['operation'] == 'prepare')
    meal_ground.update(operation='eco', grounded_operation='eco')
    fast = deepcopy(meal_ground)
    fast.update(operation='fast', grounded_operation='fast')
    episode['action_grounding'].append(fast)
    meal_tool = next(t for t in episode['tool_catalog'] if t['agent_id'] == meal['agent_id'] and t['operation'] == 'prepare')
    meal_tool.update(operation='eco', tool_name='cooktop_eco')
    fast_tool = deepcopy(meal_tool)
    fast_tool.update(operation='fast', tool_name='cooktop_fast')
    episode['tool_catalog'].append(fast_tool)
    for task in episode['task_stream']:
        tid = task['task_id']
        task['completion_deadline_ms'] = (5 if tid == 'water' else 12) * 60000
        task['goal'] = (f'Provide {tid} service. ' + ('Both eco and fast are acceptable. ' if tid != 'water' else '')
                        + 'Do not miss any task deadline; among feasible household plans, prefer earlier completion of all requests. '
                        + 'Use the current public coordination_context. Propose only your own device action.')
        duration, units = CONTRACTS[tid][task['action_template']['operation']]
        task['action_template'].update(duration_ms=duration, power_kw=units)
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        tools = [t for t in episode['tool_catalog'] if t['agent_id'] == agent['agent_id']]
        agent['tools'] = [t['tool_name'] for t in tools]
        for tool in tools:
            if tool['operation'] == 'off':
                continue
            duration, units = CONTRACTS[tid][tool['operation']]
            tool['cost_contract'] = {'duration_ms': duration, 'resource_units': units}
            tool['description'] = (f"Provide {task['requested_service']} using {tool['operation']}. "
                                   f'Declared cost: {duration} ms and {units} abstract admission units. Synthetic contract.')
            ground = next(g for g in episode['action_grounding'] if g['task_id'] == tid and g['operation'] == tool['operation'])
            ground.update(duration_ms=duration, power_kw=units)
    episode['initial_state']['values']['coordination_context'] = {
        'resource_capacity_units': capacity, 'all_tasks_released': True,
        'objective': 'all services and deadlines first; then earliest whole-house completion',
        'requests': [{'task_id': t['task_id'], 'deadline_ms': t['completion_deadline_ms'], 'requested_service': t['requested_service'],
                      'modes': [{'operation': tool['operation'], **tool['cost_contract']} for tool in episode['tool_catalog']
                                if tool['agent_id'] == t['agent_id'] and tool['provides_service'] == t['requested_service']]}
                     for t in episode['task_stream']]}
    return episode

def records_for(episode, modes, latencies):
    records = {}
    for task in episode['task_stream']:
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        request = build_agent_request(episode, agent, task, architecture='IndependentMultiAgent', current_time_ms=0)
        client = PublicModeClient(modes.get(task['task_id'], 'prepare'), latencies)
        records[task['task_id']] = {'request': request, 'decision': client.decide(request),
                                   'logical_latency_ms': latencies[task['task_id']]}
    return records

def prepare():
    hashes = {}
    for capacity in CAPACITIES:
        path = DIR / f'capacity-{capacity}.json'
        episode = build(capacity)
        if validate_event_episode(episode):
            raise ValueError(validate_event_episode(episode))
        write(path, episode)
        hashes[path.name] = digest(path)
    design = {'status': 'locked_before_dual_mode_experiments', 'candidate_sha256': hashes,
              'prereg_sha256': digest(ROOT.parent / 'docs' / 'C3_MULTIMODE_REPLICATION_PREREG_2026-09-30.md'),
              'capacities': list(CAPACITIES), 'contracts': CONTRACTS, 'scripted_runs': 360,
              'planned_api_requests': 18, 'repetitions': 2, 'max_attempts': 1,
              'policies': list(LABELS), 'limits': 'second author-designed development structure; synthetic admission units; dependent permutations'}
    write(DIR / 'manifest.json', design)
    return design

def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    if design['prereg_sha256'] != digest(ROOT.parent / 'docs' / 'C3_MULTIMODE_REPLICATION_PREREG_2026-09-30.md'):
        raise ValueError('preregistration changed')
    episodes = {}
    for name, expected in design['candidate_sha256'].items():
        if digest(DIR / name) != expected:
            raise ValueError('locked input changed')
        episode = json.loads((DIR / name).read_text(encoding='utf8'))
        if validate_event_episode(episode):
            raise ValueError('invalid episode')
        episodes[episode['home']['resources']['max_power_kw']] = episode
    return design, episodes

def offline():
    design, episodes = locked()
    rows = []
    for capacity, episode in episodes.items():
        for laundry, meal in itertools.product(('eco', 'fast'), repeat=2):
            modes = {'laundry': laundry, 'meal': meal}
            for order in itertools.permutations(('laundry', 'water', 'meal')):
                records = records_for(episode, modes, {tid: 800 + rank * 200 for rank, tid in enumerate(order)})
                for label in LABELS:
                    row = run_one(episode, records, label)
                    row.update(proposed_modes=modes, arrival_order=list(order))
                    rows.append(row)
    if len(rows) != design['scripted_runs']:
        raise ValueError('incomplete scripted grid')
    result = {'status': 'completed', 'design_sha256': digest(DIR / 'manifest.json'), 'new_api_calls': 0, 'rows': rows}
    write(OFFLINE, result)
    return result

def live():
    design, episodes = locked()
    result = json.loads(LIVE.read_text(encoding='utf8')) if LIVE.exists() else {
        'status': 'partial', 'design_sha256': digest(DIR / 'manifest.json'), 'batches': []}
    if result['design_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('design mismatch')
    LOGDIR.mkdir(parents=True, exist_ok=True)
    provider = DeepSeekResponsesClient(model='deepseek-flash', max_attempts=1,
        logger=EventLogger(LOGDIR / 'model_events.jsonl', 'c3-multimode-replication-20260930'))
    if not provider.api_key:
        raise RuntimeError('API key is not configured')
    for capacity, episode in episodes.items():
        for repetition in (1, 2):
            if any(b['capacity_units'] == capacity and b['repetition'] == repetition for b in result['batches']):
                continue
            sample = sample_parallel(provider, episode, repetition + 300)
            scores = []
            for task in episode['task_stream']:
                record = sample['records'].get(task['task_id'])
                actions = record['decision']['actions'] if record else []
                authorized = len(actions) == 1 and validate_tool_call(episode, task['agent_id'], task['task_id'], actions[0]) is None
                scores.append({'task_id': task['task_id'], 'authorized': authorized,
                    'semantic_correct': authorized and task_accepts_action(actions[0], task),
                    'operation': actions[0]['operation'] if actions else None})
            rows = [] if sample['errors'] else [run_one(episode, sample['records'], label) for label in LABELS]
            result['batches'].append({'capacity_units': capacity, 'repetition': repetition, 'sample': sample, 'scores': scores, 'rows': rows})
            write(LIVE, result)
            print(json.dumps({'capacity': capacity, 'rep': repetition, 'errors': sample['errors'], 'scores': scores}), flush=True)
    result['status'] = 'complete' if sum(len(b['rows']) for b in result['batches']) == 30 else 'complete_with_errors'
    write(LIVE, result)
    return result

def audit():
    design, episodes = locked()
    scripted, model = (json.loads(p.read_text(encoding='utf8')) for p in (OFFLINE, LIVE))
    if len(scripted['rows']) != 360 or len(model['batches']) != 6:
        raise ValueError('incomplete experiment')
    for episode in episodes.values():
        for task in episode['task_stream']:
            if task_accepts_action({'target': task['action_template']['target'], 'operation': 'off'}, task):
                raise ValueError('off scores as service')
        for tool in episode['tool_catalog']:
            ground = next(g for g in episode['action_grounding'] if g['agent_id'] == tool['agent_id'] and g['operation'] == tool['operation'])
            if tool['cost_contract'] != {'duration_ms': ground['duration_ms'], 'resource_units': ground['power_kw']}:
                raise ValueError('public/execution cost mismatch')
    pairs = []
    for batch in model['batches']:
        for record in batch['sample']['records'].values():
            if any(k in record['request']['task'] for k in ('acceptable_actions', 'required_action', 'action_template')):
                raise ValueError('hidden scoring leaked')
        if not batch['rows']:
            continue
        by_policy = {r['policy']: r for r in batch['rows']}
        fixed, flexible = (by_policy[label] for label in LABELS[-2:])
        for row in (fixed, flexible):
            if row['model_latency_by_task_ms'] != row['actual_proposal_latencies_ms']:
                raise ValueError('latencies overwritten')
            if row['plan'] and min(row['task_start_wait_ms'].values()) < row['plan']['available_at_ms'] + 100:
                raise ValueError('premature plan')
        original = {s['task_id']: s['operation'] for s in batch['scores']}
        if fixed['chosen_modes'] != original:
            raise ValueError('fixed baseline changed modes')
        pairs.append({'capacity_units': batch['capacity_units'], 'repetition': batch['repetition'],
            'proposed_modes': original, 'enumerated_modes': flexible['chosen_modes'],
            'whole_completion_improvement_ms': fixed['last_actual_completion_ms'] - flexible['last_actual_completion_ms'],
            'task_wait_change_ms': {t: flexible['task_start_wait_ms'][t] - fixed['task_start_wait_ms'][t] for t in original},
            'task_completion_change_ms': {t: flexible['task_completion_latency_ms'][t] - fixed['task_completion_latency_ms'][t] for t in original}})
    summaries = {}
    for kind, rows in (('scripted', scripted['rows']), ('new_model', [r for b in model['batches'] for r in b['rows']])):
        summaries[kind] = [{'policy': label, 'runs': sum(r['policy'] == label for r in rows),
            'all_served': sum(r['all_tasks_served'] for r in rows if r['policy'] == label),
            'all_deadlines': sum(r['all_deadlines_met'] for r in rows if r['policy'] == label),
            'zero_process_violation': sum(r['process_violation_ms'] == 0 for r in rows if r['policy'] == label)} for label in LABELS]
    logs = [json.loads(line) for line in (LOGDIR / 'model_events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    responses = [e for e in logs if e['event_type'] == 'model_call_completed']
    scores = [s for b in model['batches'] for s in b['scores']]
    result = {'status': 'audited', 'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (LIVE, OFFLINE, DIR / 'manifest.json')},
        'fresh_api_successes': len(responses), 'semantic_correct': sum(s['semantic_correct'] for s in scores),
        'summaries': summaries, 'mode_pairs': pairs, 'errors': [b['sample']['errors'] for b in model['batches'] if b['sample']['errors']],
        'input_tokens': sum(e.get('input_tokens') or 0 for e in responses), 'output_tokens': sum(e.get('output_tokens') or 0 for e in responses),
        'limits': design['limits']}
    write(AUDIT, result)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'offline', 'live', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'offline': offline, 'live': live, 'audit': audit}[stage]()
    print(json.dumps({'stage': stage, 'status': result['status'], 'rows': len(result.get('rows', []))}))
