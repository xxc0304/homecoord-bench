"""Hybrid release-state pilot: saved early proposals, fresh late request per branch."""
import argparse
import json
from copy import deepcopy
from time import perf_counter_ns
from probe_c3_action_choice_20260930 import digest, write
from probe_c3_scale_release_20260930 import ROOT, DIR as SOURCE_DIR, load
from probe_c3_information_baselines_20260930 import adapt
from probe_c3_runtime_repeat_20260930 import LIVE as SOURCE
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation, _apply_patch
from runtime.protocol import build_agent_request
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.replay_client import MemoryReplayClient
from runtime.tool_contract import validate_tool_call

DIR = ROOT / 'revision_drafts' / '20260930_c3_release_state'
OUTPUT = ROOT / 'results' / 'c3_release_state_model_20260930.json'
LOGDIR = ROOT / 'runs' / 'c3-release-state-20260930'
LABELS = ('GateRetryRule', 'ReleasedFeasibilityFallback')
PRESSURES = (1.6, 0.8)

class ReleaseStateClient:
    def __init__(self, records, provider, branch_id):
        self.records, self.provider, self.branch_id = records, provider, branch_id
        self.last_latency_ms = 0
        self.fresh = []
        self.reused = []

    def decide(self, request, instructions):
        task_id = request['task']['task_id']
        if request['current_time_ms'] == 0:
            self.reused.append(task_id)
            record = self.records[task_id]
            self.last_latency_ms = record['logical_latency_ms']
            return deepcopy(record['decision'])
        if request['current_time_ms'] != 60000 or self.fresh:
            raise ValueError('expected exactly one late request at own release')
        api_request = deepcopy(request)
        api_request['request_id'] = self.branch_id + ':' + task_id
        start = perf_counter_ns()
        decision = self.provider.decide(api_request, instructions)
        self.last_latency_ms = max(1, round((perf_counter_ns() - start) / 1e6))
        self.fresh.append({'request': deepcopy(request), 'api_request': api_request,
                           'decision': deepcopy(decision), 'logical_latency_ms': self.last_latency_ms})
        return decision

def audit_release_request(episode, trace, request):
    """Reconstruct visible state at release from preceding logged state changes."""
    state = deepcopy(episode['initial_state']['values'])
    version = episode['initial_state']['version']
    released = set()
    for event in trace['events']:
        if event['type'] == 'state_update':
            _apply_patch(state, event['patch'])
            version = event['new_state_version']
        elif event['type'] == 'action_completed':
            _apply_patch(state, event['effects'])
            version = event['new_state_version']
        elif event['type'] == 'task_released':
            released.add(event['task_id'])
            if event['task_id'] == request['task']['task_id']:
                if event['timestamp_ms'] != request['current_time_ms']:
                    raise ValueError('request clock not own release')
                agent = next(a for a in episode['agents'] if a['agent_id'] == request['agent']['agent_id'])
                task = next(t for t in episode['task_stream'] if t['task_id'] == event['task_id'])
                rebuilt = build_agent_request(episode, agent, task, architecture=trace['policy'],
                                              current_time_ms=event['timestamp_ms'], current_state=state,
                                              state_version=version, released_task_ids=released,
                                              request_id=request['request_id'])
                for field in ('state', 'state_version', 'task', 'goals', 'available_actions', 'current_time_ms'):
                    if rebuilt[field] != request[field]:
                        raise ValueError('release request mismatch: ' + field)
                if 'action_template' in request['task'] or 'required_action' in request['task']:
                    raise ValueError('scoring answer leaked')
                return {'reconstructed_at_release': True, 'state_version': version,
                        'visible_state': request['state'],
                        'visible_state_differs_from_initial': rebuilt['state'] != build_agent_request(
                            episode, agent, task, architecture=trace['policy'], current_time_ms=0,
                            released_task_ids=released)['state']}
    raise ValueError('release event absent')

def prepare():
    manifest, _ = load()
    design = {'version': 'release-state-hybrid-0.1',
              'source_model_sha256': digest(SOURCE), 'source_manifest_sha256': digest(SOURCE_DIR / 'manifest.json'),
              'candidate_sha256': manifest['candidate_sha256'], 'templates': ['N2-1', 'N4-1', 'N5-1'],
              'repetitions': [1, 2, 3], 'pressures': list(PRESSURES), 'policies': list(LABELS),
              'deadline': 'tight', 'release': 'urgent_late', 'planned_fresh_requests': 36,
              'max_attempts': 1, 'paired_saved_proposal_runs': 36,
              'fairness': 'same earlier saved proposals and return latencies per pair; late proposal and measured latency may both change',
              'scope': 'hybrid episode, not all-fresh end-to-end execution; synchronous API call at virtual release, not wall-clock concurrent simulator',
              'state_scope': 'local specialist device only; running other devices may change global version while local state remains idle',
              'status': 'locked_before_release_state_calls'}
    write(DIR / 'manifest.json', design)
    return design

def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    manifest, episodes = load()
    if digest(SOURCE) != design['source_model_sha256'] or digest(SOURCE_DIR / 'manifest.json') != design['source_manifest_sha256'] or manifest['candidate_sha256'] != design['candidate_sha256']:
        raise ValueError('locked source changed')
    return design, episodes, json.loads(SOURCE.read_text(encoding='utf8'))

def metrics(result):
    return {'all_tasks_served': all(result['task_service'].values()),
            **{k: result[k] for k in ('all_deadlines_met', 'first_action_start_latency_ms',
                                       'task_start_wait_ms', 'task_completion_tardiness_ms',
                                       'task_unstarted_count', 'model_latency_by_task_ms')}}

def run(retry_network=False):
    design, episodes, source = locked()
    result = json.loads(OUTPUT.read_text(encoding='utf8')) if OUTPUT.exists() else {
        'design_sha256': digest(DIR / 'manifest.json'), 'branches': [], 'status': 'partial'}
    if result['design_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('existing branch design changed')
    if retry_network:
        failed = [b for b in result['branches'] if '10013' in b.get('error', '')]
        result.setdefault('blocked_network_attempts', []).extend(failed)
        result['branches'] = [b for b in result['branches'] if b not in failed]
    LOGDIR.mkdir(parents=True, exist_ok=True)
    provider = DeepSeekResponsesClient(model='deepseek-flash', max_attempts=1,
                                       logger=EventLogger(LOGDIR / 'model_events.jsonl', 'c3-release-state-20260930'))
    if not provider.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not configured')
    for batch in source['batches']:
        template, rep = batch['template'], batch['repetition']
        for pressure in PRESSURES:
            episode = episodes[template, 'tight', 'urgent_late', pressure]
            for label in LABELS:
                branch_id = f'{template}:{rep}:{pressure}:{label}'
                if any(b['branch_id'] == branch_id for b in result['branches']):
                    continue
                changed, policy = adapt(episode, label) if label.startswith('Released') else (deepcopy(episode), label)
                cached = MemoryReplayClient(deepcopy(release_order_records(episode, batch['sample']['records'])))
                _, old = run_event_simulation(changed, cached, policy, '', shared_safety_gate=True)
                cached.assert_consumed()
                hybrid = ReleaseStateClient(batch['sample']['records'], provider, branch_id)
                branch = {'branch_id': branch_id, 'template': template, 'repetition': rep,
                          'pressure': pressure, 'policy': label, 'saved_proposal_control': metrics(old)}
                try:
                    trace, fresh = run_event_simulation(changed, hybrid, policy, PILOT_INSTRUCTIONS, shared_safety_gate=True)
                    if len(hybrid.fresh) != 1:
                        raise ValueError('expected one fresh late record')
                    record = hybrid.fresh[0]
                    branch['release_state_audit'] = audit_release_request(changed, trace, record['request'])
                    task = record['request']['task']
                    actions = record['decision']['actions']
                    authorized = len(actions) == 1 and validate_tool_call(changed, task['agent_id'], task['task_id'], actions[0]) is None
                    required = next(t['required_action'] for t in changed['task_stream'] if t['task_id'] == task['task_id'])
                    branch.update({'fresh_late_record': record, 'reused_early_tasks': hybrid.reused,
                                   'authorized': authorized, 'semantic_correct': authorized and all(actions[0].get(k) == v for k, v in required.items()),
                                   'fresh_release_state_result': metrics(fresh), 'trace': trace})
                except Exception as exc:
                    branch.update({'error_type': type(exc).__name__, 'error': str(exc)[:1000],
                                   'fresh_records_before_error': hybrid.fresh})
                result['branches'].append(branch)
                write(OUTPUT, result)
                print(json.dumps({'branch': branch_id, 'error': branch.get('error_type'),
                                  'correct': branch.get('semantic_correct'),
                                  'all_deadlines_met': branch.get('fresh_release_state_result', {}).get('all_deadlines_met')}), flush=True)
                if '10013' in branch.get('error', ''):
                    result['status'] = 'blocked_local_network'
                    write(OUTPUT, result)
                    return result
    good = [b for b in result['branches'] if 'fresh_release_state_result' in b]
    result['status'] = ('complete' if len(good) == design['planned_fresh_requests'] else
                        'complete_with_errors' if len(result['branches']) == design['planned_fresh_requests'] else 'partial_with_errors')
    result['planned_branches_attempted'] = len(result['branches'])
    result['completed_branches'] = len(good)
    result['semantic_correct'] = sum(b['semantic_correct'] for b in good)
    result['visible_state_changed_branches'] = sum(b['release_state_audit']['visible_state_differs_from_initial'] for b in good)
    result['deadline_result_changed_branches'] = sum(b['saved_proposal_control']['all_deadlines_met'] != b['fresh_release_state_result']['all_deadlines_met'] for b in good)
    write(OUTPUT, result)
    return result

def audit():
    design, episodes, source = locked()
    saved = json.loads(OUTPUT.read_text(encoding='utf8'))
    batches = {(b['template'], b['repetition']): b for b in source['batches']}
    rows, failed, groups = [], [], {}
    for branch in saved['branches']:
        group_key = (branch['template'], branch['pressure'], branch['policy'])
        group = groups.setdefault(group_key, {'template': branch['template'], 'pressure': branch['pressure'],
                                              'policy': branch['policy'], 'planned': 3, 'valid': 0,
                                              'protocol_or_execution_failures': 0, 'all_served': 0, 'all_deadlines': 0})
        if 'error' in branch:
            group['protocol_or_execution_failures'] += 1
            failed.append({'branch_id': branch['branch_id'], 'error_type': branch['error_type'], 'error': branch['error']})
            continue
        template, rep, pressure, label = branch['template'], branch['repetition'], branch['pressure'], branch['policy']
        episode = episodes[template, 'tight', 'urgent_late', pressure]
        changed, policy = adapt(episode, label) if label.startswith('Released') else (deepcopy(episode), label)
        record = branch['fresh_late_record']
        audit_release_request(changed, branch['trace'], record['request'])
        records = deepcopy(batches[template, rep]['sample']['records'])
        old_client = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
        old_trace, old = run_event_simulation(changed, old_client, policy, '', shared_safety_gate=True)
        old_client.assert_consumed()
        prefix = lambda trace: [(e['task_id'], e['timestamp_ms'], e['operation']) for e in trace['events']
                                if e['type'] == 'action_started' and e['timestamp_ms'] < 60000]
        if prefix(old_trace) != prefix(branch['trace']) or metrics(old) != branch['saved_proposal_control']:
            raise ValueError('paired early actions or saved control changed')
        records[record['request']['task']['task_id']] = record
        replay = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
        _, reevaluated = run_event_simulation(changed, replay, policy, '', shared_safety_gate=True)
        replay.assert_consumed()
        if metrics(reevaluated) != branch['fresh_release_state_result']:
            raise ValueError('fresh branch not reproducible from saved decisions')
        group['valid'] += 1
        group['all_served'] += int(reevaluated['task_unstarted_count'] == 0 and branch['fresh_release_state_result']['all_tasks_served'])
        group['all_deadlines'] += int(reevaluated['all_deadlines_met'])
        rows.append({'branch_id': branch['branch_id'], 'early_start_prefix_unchanged': True,
                     'fresh_metrics_reproduced': True, 'release_state_reconstructed': True,
                     'visible_state_changed': branch['release_state_audit']['visible_state_differs_from_initial'],
                     'release_state_version': record['request']['state_version'],
                     'fresh_latency_ms': record['logical_latency_ms']})
    logs = [json.loads(line) for line in (LOGDIR / 'model_events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    charged_responses = [e for e in logs if e['event_type'] in ('model_call_completed', 'model_call_failed') and e.get('input_tokens') is not None]
    report = {'status': 'completed_attempts_with_explicit_failure', 'planned_branches': design['planned_fresh_requests'],
              'attempted_branches': len(saved['branches']), 'valid_branches': len(rows), 'failed_branches': failed,
              'groups': list(groups.values()), 'rows': rows, 'new_offline_audit_runs': len(rows) * 2,
              'input_tokens_including_invalid_protocol': sum(e.get('input_tokens') or 0 for e in charged_responses),
              'output_tokens_including_invalid_protocol': sum(e.get('output_tokens') or 0 for e in charged_responses),
              'source_sha256': digest(OUTPUT), 'design_sha256': digest(DIR / 'manifest.json')}
    write(ROOT / 'results' / 'c3_release_state_audit_20260930.json', report)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'run', 'retry-network', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'run': run, 'retry-network': lambda: run(True), 'audit': audit}[stage]()
    print(json.dumps({'status': result['status'], 'completed': result.get('completed_branches'),
                      'semantic_correct': result.get('semantic_correct'),
                      'changed_deadlines': result.get('deadline_result_changed_branches')}))
