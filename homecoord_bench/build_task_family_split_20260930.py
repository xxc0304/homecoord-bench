"""Prospective structural split; development-only functional runs."""
import argparse
import hashlib
import itertools
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_structural_generalization import TaskSpec, make_episode_from_specs
from probe_c3_multimode_20260930 import PublicModeClient
from runtime.protocol import build_agent_request
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient
from probe_c3_staggered_release import release_order_records
from runtime.scheduling_oracle import ideal_schedule
from evaluate import task_accepts_action

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_task_family_split'
OUTPUT = ROOT / 'results' / 'task_family_development_20260930.json'
PREREG = ROOT.parent / 'docs' / 'TASK_FAMILY_SPLIT_PREREG_2026-09-30.md'
POLICIES = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')

def item(name, minutes, units, deadline, release=0):
    return {'name': name, 'modes': [{'operation': 'prepare', 'duration_min': minutes, 'units': units}],
            'deadline_min': deadline, 'release_min': release}

def flexible(name, eco, fast, deadline):
    return {'name': name, 'modes': [{'operation': op, 'duration_min': costs[0], 'units': costs[1]}
                                   for op, costs in (('eco', eco), ('fast', fast))],
            'deadline_min': deadline, 'release_min': 0}

def blueprints():
    definitions = [
        ('D-F1-01', 'development', 'F1', 3, [item('laundry', 8, 2, 20), item('meal', 3, 1, 7), item('dishes', 5, 1, 15)]),
        ('D-F1-02', 'development', 'F1', 4, [item('water', 4, 3, 6), item('laundry', 12, 1, 30),
            item('dishes', 7, 1, 18), item('meal', 3, 2, 12), item('cleaning', 8, 1, 25)]),
        ('D-F2-01', 'development', 'F2', 3, [item('laundry', 8, 2, 20), item('dishes', 5, 1, 16),
            item('cleaning', 6, 1, 18), item('water', 2, 2, 5, 1)]),
        ('D-F2-02', 'development', 'F2', 3, [item('meal', 3, 2, 14), item('laundry', 10, 1, 20),
            item('cleaning', 6, 2, 18), item('water', 4, 1, 7, 2)]),
        ('D-F3-01', 'development', 'F3', 3, [flexible('laundry', (9, 1), (4, 2), 16),
            item('water', 4, 2, 7), item('meal', 6, 1, 18)]),
        ('D-F3-02', 'development', 'F3', 4, [flexible('drying', (12, 1), (5, 3), 25),
            flexible('dishes', (10, 1), (6, 2), 24), item('water', 4, 2, 7), item('meal', 5, 1, 16), item('cleaning', 3, 1, 12)]),
        ('H-F1-01', 'prospective_test', 'F1', 3, [item('meal', 6, 3, 18), item('dishes', 9, 1, 18)]),
        ('H-F1-02', 'prospective_test', 'F1', 3, [item('water', 5, 2, 8), item('drying', 9, 2, 24),
            item('meal', 3, 1, 7), item('cleaning', 6, 1, 16)]),
        ('H-F2-01', 'prospective_test', 'F2', 2, [item('drying', 10, 2, 18), item('water', 3, 2, 6, 2)]),
        ('H-F2-02', 'prospective_test', 'F2', 4, [item('drying', 10, 3, 25), item('meal', 4, 1, 15),
            item('dishes', 6, 1, 20), item('cleaning', 7, 1, 22), item('water', 3, 2, 6, 2)]),
        ('H-F3-01', 'prospective_test', 'F3', 4, [flexible('drying', (10, 1), (4, 3), 20),
            flexible('dishes', (8, 1), (5, 2), 18), item('water', 4, 2, 7), item('meal', 3, 1, 12)]),
        ('H-F3-02', 'prospective_test', 'F3', 4, [flexible('laundry', (6, 1), (3, 2), 14),
            flexible('drying', (11, 2), (5, 3), 24), flexible('dishes', (8, 1), (4, 2), 18),
            item('water', 2, 2, 4), item('cleaning', 7, 1, 20)])]
    return [{'structure_id': sid, 'split': split, 'family': family, 'competition_capacity': capacity,
             'tasks': tasks, 'origin': 'author_defined_synthetic_public_service_contract',
             'independent_review': 'pending'} for sid, split, family, capacity, tasks in definitions]

def structure_signature(card):
    """Invariant to names/order and uniform scaling of time and resource units."""
    scale = max(m['duration_min'] for t in card['tasks'] for m in t['modes'])
    capacity = card['competition_capacity']
    tasks = []
    for task in card['tasks']:
        tasks.append((str(Fraction(task['release_min'], scale)), str(Fraction(task['deadline_min'], scale)),
            tuple(sorted((str(Fraction(m['duration_min'], scale)), str(Fraction(m['units'], capacity))) for m in task['modes']))))
    canonical = json.dumps(sorted(tasks), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()

def build(card, resource_arm, temporal_arm):
    specs = tuple(TaskSpec(t['name'], t['name'].title() + 'Agent', t['name'] + '_device', t['modes'][0]['operation'],
                           t['modes'][0]['units'], t['modes'][0]['duration_min'], t['deadline_min'], 100-i*5)
                  for i, t in enumerate(card['tasks']))
    episode = make_episode_from_specs(card['structure_id'], specs, 1)
    capacity = card['competition_capacity'] if resource_arm == 'competition' else sum(max(m['units'] for m in t['modes']) for t in card['tasks'])
    episode['episode_id'] = f"{card['structure_id']}-{resource_arm}-{temporal_arm}"
    episode['base_episode_id'] = card['structure_id']
    episode['split'] = card['split']
    episode['family_block'] = card['family']
    episode['pairing'] = {'resource_arm': resource_arm, 'temporal_arm': temporal_arm}
    episode['source_type'] = 'prospective_task_family_synthetic_contract'
    episode['review_status'] = 'author_candidate_not_independently_reviewed'
    episode['resource_unit'] = 'abstract_admission_unit'
    episode.pop('resource_pressure', None)
    episode['home']['resources']['max_power_kw'] = capacity
    episode['conflict_rules'][0]['capacity'] = capacity
    episode['scenario_assumptions'] = {'physical_calibration': 'none', 'resource_semantics': 'abstract admission units in legacy power_kw fields',
        'execution': 'constant load, noninterruptible, public declared costs', 'future_information': 'not given to online policy'}
    for task, source in zip(episode['task_stream'], card['tasks']):
        release = source['release_min'] * 60000 if card['family'] == 'F2' and temporal_arm == 'late' else 0
        deadline = (source['deadline_min'] - source['release_min']) * 60000 + release
        if card['family'] != 'F2' and temporal_arm == 'loose':
            deadline += 1200000
        task.update(release_at_ms=release, completion_deadline_ms=deadline, requested_service=source['name'] + '_completed')
        task['acceptable_actions'] = [task.pop('required_action')]
        operations = [m['operation'] for m in source['modes']]
        task['goal'] = (f"Provide {source['name']} service. Acceptable modes: {', '.join(operations)}. "
                        f"Complete within {deadline-release} ms of this task release. Use only your own authorized tools. "
                        'All services and deadlines first; prefer earlier whole-house completion when feasible.')
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        tool = next(t for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id'])
        ground = next(g for g in episode['action_grounding'] if g['task_id'] == task['task_id'])
        for index, mode in enumerate(source['modes']):
            mode_tool, mode_ground = (tool, ground) if index == 0 else (deepcopy(tool), deepcopy(ground))
            mode_tool.update(operation=mode['operation'], tool_name=source['name'] + '_' + mode['operation'],
                provides_service=task['requested_service'],
                cost_contract={'duration_ms': mode['duration_min'] * 60000, 'resource_units': mode['units']},
                description=f"Provides {task['requested_service']}; synthetic contract {mode['duration_min']*60000}ms/{mode['units']} admission units.")
            mode_ground.update(operation=mode['operation'], grounded_operation=mode['operation'],
                               duration_ms=mode['duration_min'] * 60000, power_kw=mode['units'])
            if index:
                episode['tool_catalog'].append(mode_tool)
                episode['action_grounding'].append(mode_ground)
                task['acceptable_actions'].append({'target': tool['target'], 'operation': mode['operation']})
        off_tool = deepcopy(tool)
        off_tool.update(operation='off', tool_name=source['name'] + '_off', provides_service='none',
                        cost_contract={'duration_ms': 100, 'resource_units': 0}, description='Leave idle; does not provide requested service.')
        episode['tool_catalog'].append(off_tool)
        off_ground = deepcopy(ground)
        off_ground.update(operation='off', grounded_operation='off', duration_ms=100, power_kw=0,
                          start_effects={}, effects={}, completion_effects={})
        episode['action_grounding'].append(off_ground)
        agent['tools'] = [t['tool_name'] for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id']]
        agent['observable_state'].append('coordination_context')
        episode['home']['resources']['task_power_bounds_kw'][task['task_id']] = max(m['units'] for m in source['modes'])
    # F2 requests are projected at release below; no future costs/goals are exposed.
    episode['initial_state']['values']['coordination_context'] = public_context(episode, 0)
    if card['family'] == 'F2' and temporal_arm == 'late':
        for at in sorted({t['release_at_ms'] for t in episode['task_stream'] if t['release_at_ms'] > 0}):
            episode['exogenous_events'].append({'event': 'new_public_request', 'at_ms': at,
                'patch': {'coordination_context': public_context(episode, at)}})
    return episode

def public_context(episode, at_ms):
    return {'resource_capacity_units': episode['home']['resources']['max_power_kw'],
        'objective': 'all services/deadlines then earlier whole-house completion',
        'requests': [{'task_id': task['task_id'], 'deadline_ms': task['completion_deadline_ms'],
            'release_at_ms': task['release_at_ms'], 'requested_service': task['requested_service'],
            'modes': [{'operation': tool['operation'], **tool['cost_contract']} for tool in episode['tool_catalog']
                      if tool['agent_id'] == task['agent_id'] and tool['provides_service'] == task['requested_service']]}
            for task in episode['task_stream'] if task['release_at_ms'] <= at_ms]}

def static_check(episode):
    errors = validate_event_episode(episode)
    if errors:
        raise ValueError(errors)
    for task in episode['task_stream']:
        if task_accepts_action({'target': task['action_template']['target'], 'operation': 'off'}, task):
            raise ValueError('off provides service')
    for tool in episode['tool_catalog']:
        ground = next(g for g in episode['action_grounding'] if g['agent_id'] == tool['agent_id'] and g['operation'] == tool['operation'])
        if tool['cost_contract'] != {'duration_ms': ground['duration_ms'], 'resource_units': ground['power_kw']}:
            raise ValueError('public/execution cost mismatch')

def prepare():
    if (DIR / 'manifest.json').exists():
        raise ValueError('split already locked; use audit, do not regenerate this version')
    cards = blueprints()
    signatures = {}
    candidates = []
    for card in cards:
        signature = structure_signature(card)
        if signature in signatures:
            raise ValueError('duplicate or uniformly rescaled structure')
        signatures[signature] = card['split']
        temporal = ('simultaneous', 'late') if card['family'] == 'F2' else ('base', 'loose')
        for resource_arm, temporal_arm in itertools.product(('competition', 'no_competition'), temporal):
            episode = build(card, resource_arm, temporal_arm)
            static_check(episode)
            path = DIR / card['split'] / (episode['episode_id'] + '.json')
            write(path, episode)
            candidates.append({'episode_id': episode['episode_id'], 'structure_id': card['structure_id'],
                'split': card['split'], 'family': card['family'], 'agent_count': len(card['tasks']),
                'normalized_structure_sha256': signature, 'path': str(path.relative_to(ROOT)), 'sha256': digest(path)})
    write(DIR / 'blueprints.json', cards)
    manifest = {'status': 'locked_before_development_runs', 'prereg_sha256': digest(PREREG),
        'blueprints_sha256': digest(DIR / 'blueprints.json'), 'candidates': candidates,
        'structures': 12, 'development_episodes': 24, 'prospective_test_episodes': 24,
        'test_status': 'sealed_unexecuted_only_static_validation', 'new_api_calls': 0,
        'limits': 'author defined; not independent review; legacy all development; prospective structures, not external test'}
    write(DIR / 'manifest.json', manifest)
    return manifest

def locked_development():
    manifest = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    if digest(PREREG) != manifest['prereg_sha256'] or digest(DIR / 'blueprints.json') != manifest['blueprints_sha256']:
        raise ValueError('locked scheme changed')
    episodes = []
    for entry in manifest['candidates']:
        path = ROOT / entry['path']
        if digest(path) != entry['sha256']:
            raise ValueError('candidate changed')
        if entry['split'] == 'development':
            episode = json.loads(path.read_text(encoding='utf8'))
            if episode['split'] != 'development' or episode['base_episode_id'] != entry['structure_id']:
                raise ValueError('split metadata mismatch; refusing to run a test candidate')
            episodes.append(episode)
    return manifest, episodes

class FamilyScriptClient(PublicModeClient):
    def __init__(self, modes, latencies):
        super().__init__('prepare', latencies)
        self.modes = modes
    def decide(self, request, instructions=''):
        self.mode = self.modes[request['task']['task_id']]
        return super().decide(request, instructions)

def records_for(episode, modes, latencies):
    records = {}
    for task in episode['task_stream']:
        changed = deepcopy(episode)
        changed['initial_state']['values']['coordination_context'] = public_context(episode, task['release_at_ms'])
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        request = build_agent_request(changed, agent, task, architecture='IndependentMultiAgent', current_time_ms=task['release_at_ms'])
        client = FamilyScriptClient(modes, latencies)
        records[task['task_id']] = {'request': request, 'decision': client.decide(request), 'logical_latency_ms': latencies[task['task_id']]}
    return records

def development():
    manifest, episodes = locked_development()
    rows, feasibility = [], []
    for episode in episodes:
        choices = [[tool['operation'] for tool in episode['tool_catalog'] if tool['agent_id'] == task['agent_id']
                    and tool['provides_service'] == task['requested_service']] for task in episode['task_stream']]
        ids = [t['task_id'] for t in episode['task_stream']]
        for operations in itertools.product(*choices):
            modes = dict(zip(ids, operations))
            for order_index, order in enumerate((ids, list(reversed(ids)), ids[1:] + ids[:1])):
                records = records_for(episode, modes, {tid: 800 + rank * 200 for rank, tid in enumerate(order)})
                for policy in POLICIES:
                    client = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
                    trace, result = run_event_simulation(episode, client, policy, '', shared_safety_gate=True)
                    client.assert_consumed()
                    rows.append({'episode_id': episode['episode_id'], 'structure_id': episode['base_episode_id'],
                        'family': episode['family_block'], 'policy': policy, 'arrival_order_index': order_index,
                        'proposed_modes': modes, 'all_tasks_served': all(result['task_service'].values()),
                        'all_deadlines_met': result['all_deadlines_met'], 'task_start_wait_ms': result['task_start_wait_ms'],
                        'task_completion_latency_ms': result['task_completion_latency_ms'],
                        'process_violation_ms': result['state_constraint_violation_duration_ms']})
            # This known-demand diagnostic is separated from online policy results.
            changed = deepcopy(episode)
            for task in changed['task_stream']:
                tool = next(t for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id'] and t['operation'] == modes[task['task_id']])
                task['action_template'].update(operation=tool['operation'], duration_ms=tool['cost_contract']['duration_ms'],
                                               power_kw=tool['cost_contract']['resource_units'])
                task['release_at_ms'] += 2100  # conservative declared release->proposal->command readiness bound
            schedule = ideal_schedule(changed)
            feasibility.append({'episode_id': episode['episode_id'], 'proposed_modes': modes,
                'known_all_requests_feasible': schedule is not None, 'certificate': schedule,
                'information_class': 'all_requests_known_diagnostic_not_online_baseline'})
    if len(rows) != 360:
        raise ValueError('development grid incomplete')
    summaries = []
    for family, policy in itertools.product(('F1', 'F2', 'F3'), POLICIES):
        selected = [r for r in rows if r['family'] == family and r['policy'] == policy]
        summaries.append({'family': family, 'policy': policy, 'runs': len(selected),
            'all_served': sum(r['all_tasks_served'] for r in selected),
            'all_deadlines': sum(r['all_deadlines_met'] for r in selected),
            'zero_process_violation': sum(r['process_violation_ms'] == 0 for r in selected)})
    result = {'status': 'development_functional_validation_only', 'manifest_sha256': digest(DIR / 'manifest.json'),
        'new_api_calls': 0, 'structures_run': 6, 'development_episodes_run': 24, 'scripted_runs': len(rows),
        'test_episodes_run': 0, 'test_status': manifest['test_status'], 'summaries': summaries,
        'rows': rows, 'feasibility_diagnostics': feasibility,
        'limits': 'scripted development functional runs; no model performance, no complete compute cost, no held-out outcome'}
    write(OUTPUT, result)
    return result

def audit():
    manifest, episodes = locked_development()
    groups = {}
    signatures = {}
    for entry in manifest['candidates']:
        groups.setdefault(entry['structure_id'], set()).add(entry['split'])
        signatures.setdefault(entry['normalized_structure_sha256'], set()).add(entry['split'])
    if any(len(s) != 1 for s in groups.values()) or any(len(s) != 1 for s in signatures.values()):
        raise ValueError('pairing group or normalized topology crosses split')
    if len(groups) != 12 or len(episodes) != 24:
        raise ValueError('unexpected structural split size')
    result = json.loads(OUTPUT.read_text(encoding='utf8'))
    if result['manifest_sha256'] != digest(DIR / 'manifest.json') or result['test_episodes_run'] != 0:
        raise ValueError('manifest changed or test was exposed in development result')
    allowed = {e['episode_id'] for e in episodes}
    if any(r['episode_id'] not in allowed for r in result['rows'] + result['feasibility_diagnostics']):
        raise ValueError('development output contains a held-out task')
    by_id = {e['episode_id']: e for e in episodes}
    no_competition = [r for r in result['rows'] if by_id[r['episode_id']]['pairing']['resource_arm'] == 'no_competition']
    for row in result['rows']:
        episode = by_id[row['episode_id']]
        if not row['all_tasks_served'] or row['process_violation_ms']:
            raise ValueError('functional service or safety issue; report before using these candidates')
        for task in episode['task_stream']:
            wait, completion = row['task_start_wait_ms'][task['task_id']], row['task_completion_latency_ms'][task['task_id']]
            tool = next(t for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id'] and t['operation'] == row['proposed_modes'][task['task_id']])
            if wait is None or completion - wait != tool['cost_contract']['duration_ms']:
                raise ValueError('actual mode duration not bound to response metrics')
    audited = {'status': 'audited_prospective_split_development_only', 'new_api_calls': 0,
        'source_sha256': digest(OUTPUT), 'manifest_sha256': digest(DIR / 'manifest.json'),
        'development_structures': 6, 'prospective_test_structures': 6, 'development_episodes': 24,
        'prospective_test_episodes': 24, 'test_episodes_run': 0, 'scripted_development_runs': len(result['rows']),
        'known_demand_feasibility_diagnostics': len(result['feasibility_diagnostics']),
        'known_demand_feasible': sum(d['known_all_requests_feasible'] for d in result['feasibility_diagnostics']),
        'no_competition_runs': len(no_competition), 'no_competition_all_deadlines': sum(r['all_deadlines_met'] for r in no_competition),
        'summaries': result['summaries'], 'limits': result['limits']}
    write(ROOT / 'results' / 'task_family_split_audit_20260930.json', audited)
    return audited

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'development', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'development': development, 'audit': audit}[stage]()
    print(json.dumps({k: v for k, v in result.items() if k not in ('candidates', 'rows', 'feasibility_diagnostics')}, ensure_ascii=False))
