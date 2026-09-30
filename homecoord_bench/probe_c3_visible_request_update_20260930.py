"""Visible household request changes, isolated from equal-cost scheduling."""
import argparse
import json
from copy import deepcopy
from probe_c3_action_choice_20260930 import digest, write
from probe_c3_scale_release_20260930 import ROOT, load, OPTIONS, checked_schedule
from probe_c3_information_baselines_20260930 import adapt, contracts
from probe_c3_runtime_repeat_20260930 import LIVE as SOURCE
from probe_c3_release_state_20260930 import ReleaseStateClient, audit_release_request, metrics
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation
from runtime.event_log import EventLogger
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.replay_client import MemoryReplayClient
from runtime.tool_contract import validate_tool_call
from runtime.episode_validation import validate_event_episode

DIR = ROOT / 'revision_drafts' / '20260930_c3_visible_request_update'
OUTPUT = ROOT / 'results' / 'c3_visible_request_update_model_20260930.json'
OFFLINE = ROOT / 'results' / 'c3_visible_request_update_preflight_20260930.json'
LOGDIR = ROOT / 'runs' / 'c3-visible-request-update-20260930'
ARMS = {'stable_A': (0, 0), 'A_to_B': (0, 1), 'stable_B': (1, 1), 'B_to_A': (1, 0)}
LABELS = ('GateRetryRule', 'ReleasedFeasibilityFallback')
TEMPLATES = ('N2-1', 'N4-1', 'N5-1')

def build(source, arm):
    episode = deepcopy(source)
    late = next(t for t in episode['task_stream'] if t['release_at_ms'] == 60000)
    device = late['required_action']['target']
    original = int(late['required_action']['operation'].split('_')[-1]) - 1
    first, final = (original if x == 0 else 1 - original for x in ARMS[arm])
    path = 'household_requests.' + device
    episode['episode_id'] += '-visible-' + arm
    episode['base_episode_id'] += '-visible'
    episode['source_type'] = 'controlled_visible_request_update'
    episode['initial_state']['values']['household_requests'] = {
        device: {'revision': 1, 'requirement': OPTIONS[device][first][0]}}
    episode['exogenous_events'] = ([] if first == final else [
        {'at_ms': 30000, 'event': 'household_request_revision',
         'patch': {path: {'revision': 2, 'requirement': OPTIONS[device][final][0]}}}])
    late['goal'] = ('Provide the service required by the CURRENT household request record for your device '
                    'in the supplied state. Use that record to select the service from your available actions. '
                    f"Finish within {(late['completion_deadline_ms'] - late['release_at_ms']) // 60000} minutes after release.")
    operation = f'preset_{final + 1}'
    late['required_action']['operation'] = operation
    late['action_template']['operation'] = operation
    agent = next(a for a in episode['agents'] if a['agent_id'] == late['agent_id'])
    agent['observable_state'].append(path)
    for goal in episode['goals']:
        if goal['path'] == 'services.' + device:
            goal['value'] = OPTIONS[device][final][2]
    episode['visible_update_design'] = {'arm': arm, 'late_task_id': late['task_id'],
                                      'device': device, 'initial_mode': first, 'current_mode': final,
                                      'updated': first != final, 'update_at_ms': 30000 if first != final else None,
                                      'release_at_ms': 60000}
    return episode

def adapted(episode, label):
    return adapt(episode, label) if label.startswith('Released') else (deepcopy(episode), label)

class ReferenceSelector:
    """Diagnostic known mode selector, not a proposed coordination method."""
    def __init__(self, prototype, operation):
        self.prototype, self.operation = prototype, operation
    def decide(self, request, instructions):
        decision = deepcopy(self.prototype)
        action = decision['actions'][0]
        action['operation'] = self.operation
        action['proposal_id'] = request['request_id'] + ':reference'
        action['based_on_state_version'] = request['state_version']
        return decision

def prepare():
    _, sources = load()
    candidates = {}
    for template in TEMPLATES:
        for pressure in (1.6, 0.8):
            for arm in ARMS:
                filename = f'{template}-{pressure}-{arm}.json'
                write(DIR / filename, build(sources[template, 'tight', 'urgent_late', pressure], arm))
                candidates[filename] = digest(DIR / filename)
    design = {'version': 'visible-request-update-0.1', 'source_model_sha256': digest(SOURCE),
              'candidate_sha256': candidates, 'templates': list(TEMPLATES), 'arms': ARMS,
              'fresh_sampling': 'ReleasedFeasibilityFallback / pressure1.6 / reps1,2 / all arms',
              'planned_fresh_requests': 24, 'max_attempts': 1,
              'replays_per_fresh_branch': 'two pressures by two policies, 96 total',
              'controls': 'stable in both modes; both update directions; low pressure; diagnostic current vs frozen mode',
              'isolated_costs': 'two service presets have identical public duration and power',
              'scope': 'late-only hybrid calls; early proposals reused; preference known at release, not replanning during own task execution',
              'status': 'locked_before_preflight_and_model_calls'}
    write(DIR / 'manifest.json', design)
    return design

def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    if digest(SOURCE) != design['source_model_sha256']:
        raise ValueError('source model changed')
    episodes = {}
    for filename, expected in design['candidate_sha256'].items():
        if digest(DIR / filename) != expected:
            raise ValueError('candidate changed')
        episode = json.loads((DIR / filename).read_text(encoding='utf8'))
        episodes[episode['design_factors']['template'], episode['design_factors']['pressure'], episode['visible_update_design']['arm']] = episode
    source = json.loads(SOURCE.read_text(encoding='utf8'))
    batches = {(b['template'], b['repetition']): b for b in source['batches']}
    return design, episodes, batches

def preflight():
    design, episodes, batches = locked()
    rows = []
    for (template, pressure, arm), episode in episodes.items():
        if validate_event_episode(episode) or checked_schedule(episode) is None:
            raise ValueError('invalid or intrinsically infeasible new cell')
        contracts(episode)
        records = batches[template, 1]['sample']['records']
        task_id = episode['visible_update_design']['late_task_id']
        for label in LABELS:
            changed, policy = adapted(episode, label)
            for view in ('current', 'frozen_initial'):
                mode = episode['visible_update_design']['current_mode' if view == 'current' else 'initial_mode']
                provider = ReferenceSelector(records[task_id]['decision'], f'preset_{mode + 1}')
                hybrid = ReleaseStateClient(records, provider, 'preflight')
                trace, result = run_event_simulation(changed, hybrid, policy, PILOT_INSTRUCTIONS, shared_safety_gate=True)
                audit = audit_release_request(changed, trace, hybrid.fresh[0]['request'])
                if audit['visible_state_differs_from_initial'] != episode['visible_update_design']['updated']:
                    raise ValueError('visible intervention not reaching request')
                rows.append({'template': template, 'pressure': pressure, 'arm': arm, 'policy': label,
                             'diagnostic_selector': view, 'required_service_completed': result['task_service'][task_id],
                             'all_tasks_served': all(result['task_service'].values()),
                             'all_deadlines_met': result['all_deadlines_met'], 'release_state_audit': audit})
    result = {'status': 'preflight_feasible_visible_and_equal_cost', 'new_api_calls': 0,
              'candidates': len(episodes), 'rows': rows, 'design_sha256': digest(DIR / 'manifest.json')}
    write(OFFLINE, result)
    return result

def replay_branch(episodes, records, template, arm, fresh_record):
    rows = []
    for pressure in (1.6, 0.8):
        episode = episodes[template, pressure, arm]
        for label in LABELS:
            changed, policy = adapted(episode, label)
            combined = deepcopy(records)
            combined[episode['visible_update_design']['late_task_id']] = fresh_record
            replay = MemoryReplayClient(deepcopy(release_order_records(episode, combined)))
            _, result = run_event_simulation(changed, replay, policy, '', shared_safety_gate=True)
            replay.assert_consumed()
            rows.append({'pressure': pressure, 'policy': label, **metrics(result)})
    return rows

def run(retry_network=False):
    design, episodes, batches = locked()
    check = json.loads(OFFLINE.read_text(encoding='utf8'))
    if check['design_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('preflight does not match locked design')
    result = json.loads(OUTPUT.read_text(encoding='utf8')) if OUTPUT.exists() else {
        'design_sha256': digest(DIR / 'manifest.json'), 'branches': [], 'status': 'partial'}
    if result['design_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('existing model result has different design')
    if retry_network:
        blocked = [b for b in result['branches'] if '10013' in b.get('error', '')]
        result.setdefault('blocked_network_attempts', []).extend(blocked)
        result['branches'] = [b for b in result['branches'] if b not in blocked]
    LOGDIR.mkdir(parents=True, exist_ok=True)
    provider = DeepSeekResponsesClient(model='deepseek-flash', max_attempts=1,
                                       logger=EventLogger(LOGDIR / 'model_events.jsonl', 'c3-visible-request-update-20260930'))
    if not provider.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not configured')
    for template in TEMPLATES:
        for rep in (1, 2):
            records = batches[template, rep]['sample']['records']
            for arm in ARMS:
                branch_id = f'{template}:{rep}:{arm}'
                if any(b['branch_id'] == branch_id for b in result['branches']):
                    continue
                episode = episodes[template, 1.6, arm]
                changed, policy = adapted(episode, 'ReleasedFeasibilityFallback')
                client = ReleaseStateClient(records, provider, branch_id)
                branch = {'branch_id': branch_id, 'template': template, 'repetition': rep, 'arm': arm}
                try:
                    trace, score = run_event_simulation(changed, client, policy, PILOT_INSTRUCTIONS, shared_safety_gate=True)
                    record = client.fresh[0]
                    audit = audit_release_request(changed, trace, record['request'])
                    if audit['visible_state_differs_from_initial'] != episode['visible_update_design']['updated']:
                        raise ValueError('visible state intervention missing')
                    actions = record['decision']['actions']
                    task_id = episode['visible_update_design']['late_task_id']
                    task = next(t for t in episode['task_stream'] if t['task_id'] == task_id)
                    authorized = len(actions) == 1 and validate_tool_call(changed, task['agent_id'], task_id, actions[0]) is None
                    correct = authorized and all(actions[0].get(k) == v for k, v in task['required_action'].items())
                    replay = replay_branch(episodes, records, template, arm, record)
                    live_row = next(r for r in replay if r['pressure'] == 1.6 and r['policy'] == 'ReleasedFeasibilityFallback')
                    if any(live_row[k] != v for k, v in metrics(score).items()):
                        raise ValueError('fresh live branch cannot be reproduced')
                    branch.update({'fresh_record': record, 'authorized': authorized, 'semantic_correct': correct,
                                   'release_state_audit': audit, 'live_result': metrics(score), 'replays': replay, 'trace': trace})
                except Exception as exc:
                    branch.update({'error_type': type(exc).__name__, 'error': str(exc)[:1000], 'fresh_records_before_error': client.fresh})
                result['branches'].append(branch)
                write(OUTPUT, result)
                print(json.dumps({'branch': branch_id, 'correct': branch.get('semantic_correct'), 'error': branch.get('error_type')}), flush=True)
                if '10013' in branch.get('error', ''):
                    result['status'] = 'blocked_local_network'
                    write(OUTPUT, result)
                    return result
    good = [b for b in result['branches'] if 'live_result' in b]
    result.update({'status': 'complete' if len(good) == 24 else 'complete_with_errors',
                   'valid_branches': len(good), 'semantic_correct': sum(b['semantic_correct'] for b in good),
                   'visible_update_branches': sum(b['release_state_audit']['visible_state_differs_from_initial'] for b in good),
                   'replay_count': sum(len(b['replays']) for b in good)})
    write(OUTPUT, result)
    return result

def audit():
    design, episodes, batches = locked()
    model = json.loads(OUTPUT.read_text(encoding='utf8'))
    pre = json.loads(OFFLINE.read_text(encoding='utf8'))
    if model['status'] != 'complete' or len(model['branches']) != design['planned_fresh_requests']:
        raise ValueError('model branches incomplete; do not suppress errors')
    if len(pre['rows']) != 96:
        raise ValueError('preflight incomplete')
    for row in pre['rows']:
        expected = row['diagnostic_selector'] == 'current' or not row['release_state_audit']['visible_state_differs_from_initial']
        if row['required_service_completed'] != expected:
            raise ValueError('semantic diagnostic no longer isolates request updates')
    groups = {}
    for branch in model['branches']:
        episode = episodes[branch['template'], 1.6, branch['arm']]
        changed, _ = adapted(episode, 'ReleasedFeasibilityFallback')
        audit_release_request(changed, branch['trace'], branch['fresh_record']['request'])
        for row in branch['replays']:
            key = (branch['template'], row['pressure'], row['policy'])
            group = groups.setdefault(key, {'template': key[0], 'pressure': key[1], 'policy': key[2],
                                             'runs': 0, 'all_served': 0, 'all_deadlines': 0})
            group['runs'] += 1
            group['all_served'] += int(row['all_tasks_served'])
            group['all_deadlines'] += int(row['all_deadlines_met'])
    if len(groups) != 12 or any(g['runs'] != 8 for g in groups.values()):
        raise ValueError('unbalanced replay grid')
    logs = [json.loads(line) for line in (LOGDIR / 'model_events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    successful = [e for e in logs if e['event_type'] == 'model_call_completed']
    if len(successful) != 24:
        raise ValueError('unexpected API count')
    report = {'status': 'audited_visible_update_pilot',
              'sources_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (OUTPUT, OFFLINE, DIR / 'manifest.json')},
              'fresh_successful_requests': 24, 'authorized': sum(b['authorized'] for b in model['branches']),
              'semantic_correct': sum(b['semantic_correct'] for b in model['branches']),
              'updated_state_branches': sum(b['release_state_audit']['visible_state_differs_from_initial'] for b in model['branches']),
              'preflight_rows': len(pre['rows']), 'replay_rows': 96, 'groups': list(groups.values()),
              'input_tokens': sum(e.get('input_tokens') or 0 for e in successful),
              'output_tokens': sum(e.get('output_tokens') or 0 for e in successful),
              'new_late_latency_range_ms': [min(b['fresh_record']['logical_latency_ms'] for b in model['branches']),
                                            max(b['fresh_record']['logical_latency_ms'] for b in model['branches'])],
              'limits': design['scope']}
    write(ROOT / 'results' / 'c3_visible_request_update_audit_20260930.json', report)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'preflight', 'run', 'retry-network', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'preflight': preflight, 'run': run, 'retry-network': lambda: run(True), 'audit': audit}[stage]()
    print(json.dumps({'stage': stage, 'status': result['status'], 'valid': result.get('valid_branches'),
                      'correct': result.get('semantic_correct'), 'replays': result.get('replay_count'),
                      'preflight_rows': len(result.get('rows', []))}))
