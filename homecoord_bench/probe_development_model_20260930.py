"""Bounded development model pilot: parallel early proposals, fresh late state."""
import argparse
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns
from threading import Lock
from build_task_family_split_20260930 import locked_development, DIR as SOURCE_DIR
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_parallel_model_pilot import sample_parallel
from probe_c3_multimode_20260930 import run_one
from probe_c3_staggered_release import release_order_records
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient
from runtime.protocol import assert_agent_decision
from runtime.tool_contract import validate_tool_call
from evaluate import task_accepts_action

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_development_model'
LIVE = ROOT / 'results' / 'development_model_20260930.json'
LOGDIR = ROOT / 'runs' / 'development-model-20260930'
PREREG = ROOT.parent / 'docs' / 'DEVELOPMENT_MODEL_PROTOCOL_2026-09-30.md'
FIXED = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')
LATE_LABELS = FIXED + ('ReleasedFeasibilityFallback',)

class BoundedClient:
    def __init__(self, provider, already_attempted=0, limit=26):
        self.provider, self.attempts, self.limit = provider, already_attempted, limit
        self.api_key = provider.api_key
        self.lock = Lock()
    def decide(self, request, instructions=''):
        with self.lock:
            if self.attempts >= self.limit:
                raise RuntimeError('preregistered API request limit reached; no new call')
            self.attempts += 1
        return self.provider.decide(request, instructions)

def prepare():
    if (DIR / 'manifest.json').exists():
        raise ValueError('pilot already locked; use live/audit')
    _, episodes = locked_development()
    selected = [e for e in episodes if e['base_episode_id'] in ('D-F1-01', 'D-F2-01', 'D-F3-01')
                and e['pairing']['temporal_arm'] == ('late' if e['family_block'] == 'F2' else 'base')]
    hashes = {}
    for index, source in enumerate(selected, 1):
        episode = deepcopy(source)
        episode['source_development_episode_id'] = source['episode_id']
        episode['episode_id'] = episode['base_episode_id'] = f'HC-DEV-P{index:02d}'
        path = DIR / (episode['episode_id'] + '.json')
        write(path, episode)
        hashes[path.name] = digest(path)
    design = {'status': 'locked_before_fresh_development_model_calls', 'model': 'deepseek-flash',
        'candidate_sha256': hashes, 'prereg_sha256': digest(PREREG),
        'source_split_manifest_sha256': digest(SOURCE_DIR / 'manifest.json'),
        'max_api_requests': 26, 'max_attempts': 1, 'max_output_tokens': 1200,
        'max_policy_runs': 26, 'repetitions': 1, 'test_episodes_run': 0}
    write(DIR / 'manifest.json', design)
    return design

def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    locked_development()
    if digest(PREREG) != design['prereg_sha256'] or digest(SOURCE_DIR / 'manifest.json') != design['source_split_manifest_sha256']:
        raise ValueError('locked protocol changed')
    episodes = []
    for filename, expected in design['candidate_sha256'].items():
        if digest(DIR / filename) != expected:
            raise ValueError('pilot input changed')
        episode = json.loads((DIR / filename).read_text(encoding='utf8'))
        if episode['split'] != 'development':
            raise ValueError('test candidate forbidden')
        episodes.append(episode)
    return design, episodes

def score(episode, task_id, record):
    task = next(t for t in episode['task_stream'] if t['task_id'] == task_id)
    actions = record['decision']['actions'] if record else []
    authorized = len(actions) == 1 and validate_tool_call(episode, task['agent_id'], task_id, actions[0]) is None
    return {'task_id': task_id, 'authorized': authorized, 'semantic_correct': authorized and task_accepts_action(actions[0], task),
            'operation': actions[0]['operation'] if actions else None}

class LateStateClient:
    include_evaluation_hints = False
    def __init__(self, provider, episode, early_records):
        self.provider, self.episode, self.early = provider, episode, early_records
        self.records, self.errors = {}, {}
        self.last_latency_ms = 0
    def decide(self, request, instructions=''):
        task_id = request['task']['task_id']
        if task_id in self.early:
            record = self.early[task_id]
            self.last_latency_ms = record['logical_latency_ms']
            return deepcopy(record['decision'])
        started = perf_counter_ns()
        try:
            decision = self.provider.decide(request, PILOT_INSTRUCTIONS)
        except Exception as exc:
            self.errors[task_id] = {'error_type': type(exc).__name__, 'error': str(exc)[:1000]}
            self.last_latency_ms = max(1, round((perf_counter_ns() - started) / 1e6))
            return {'response_type': 'defer', 'actions': [], 'accepted_proposal_ids': [], 'rejected_proposal_ids': [],
                    'defer_until_ms': None, 'reason_code': 'awaiting_state'}
        self.last_latency_ms = max(1, round((perf_counter_ns() - started) / 1e6))
        self.records[task_id] = {'request': deepcopy(request), 'decision': decision, 'logical_latency_ms': self.last_latency_ms}
        return decision

def late_run(episode, early_records, label, provider):
    changed = deepcopy(episode)
    policy = 'ObservedTaskFeasibilityCoordinator' if label == 'ReleasedFeasibilityFallback' else label
    changed['simulation']['observed_feasibility_fallback'] = label == 'ReleasedFeasibilityFallback'
    # F2 has exactly one public cost per service; hidden templates are audited
    # against those contracts before the feasibility baseline is allowed.
    for task in changed['task_stream']:
        tool = next(t for t in changed['tool_catalog'] if t['agent_id'] == task['agent_id'] and t['provides_service'] == task['requested_service'])
        task['action_template'].update(operation=tool['operation'], duration_ms=tool['cost_contract']['duration_ms'],
                                       power_kw=tool['cost_contract']['resource_units'])
    client = LateStateClient(provider, changed, early_records)
    trace, result = run_event_simulation(changed, client, policy, '', shared_safety_gate=True)
    late_tasks = [t for t in changed['task_stream'] if t['release_at_ms'] > 0]
    request_audits = []
    for task in late_tasks:
        runtime_request = next(r for r in trace['agent_requests'] if r['task']['task_id'] == task['task_id'])
        saved = client.records.get(task['task_id'])
        if saved and saved['request'] != runtime_request:
            raise ValueError('late provider did not receive exact release-state request')
        context = runtime_request['state']['coordination_context']['requests']
        expected_ids = {t['task_id'] for t in changed['task_stream'] if t['release_at_ms'] <= runtime_request['current_time_ms']}
        if {r['task_id'] for r in context} != expected_ids:
            raise ValueError('missing released task or future leak')
        request_audits.append({'task_id': task['task_id'], 'current_time_ms': runtime_request['current_time_ms'],
            'state_version': runtime_request['state_version'], 'request_matches_runtime': saved is not None,
            'visible_state': runtime_request['state'], 'model_latency_ms': result['model_latency_by_task_ms'][task['task_id']]})
    completion_times = [e['timestamp_ms'] for e in trace['events'] if e['type'] == 'action_completed']
    return {'policy': label, 'information_class': 'released_only', 'mode_authority': 'fixed_proposal',
        'all_tasks_served': all(result['task_service'].values()), 'all_deadlines_met': result['all_deadlines_met'],
        'task_start_wait_ms': result['task_start_wait_ms'], 'task_completion_latency_ms': result['task_completion_latency_ms'],
        'last_actual_completion_ms': max(completion_times, default=None),
        'process_violation_ms': result['state_constraint_violation_duration_ms'],
        'late_records': client.records, 'late_errors': client.errors, 'late_request_audits': request_audits,
        'scores': [score(episode, task['task_id'], client.records.get(task['task_id'])) for task in late_tasks],
        'trace': trace, 'model_latency_by_task_ms': result['model_latency_by_task_ms']}

def live():
    design, episodes = locked()
    result = json.loads(LIVE.read_text(encoding='utf8')) if LIVE.exists() else {
        'status': 'partial', 'design_sha256': digest(DIR / 'manifest.json'), 'conditions': []}
    if result['design_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('existing result design mismatch')
    LOGDIR.mkdir(parents=True, exist_ok=True)
    raw_provider = DeepSeekResponsesClient(model=design['model'], max_attempts=1, timeout_seconds=45,
        logger=EventLogger(LOGDIR / 'model_events.jsonl', 'development-model-20260930'))
    log_path = LOGDIR / 'model_events.jsonl'
    already = sum(json.loads(line)['event_type'] == 'model_call_started'
                  for line in log_path.read_text(encoding='utf8').splitlines() if line.strip()) if log_path.exists() else 0
    provider = BoundedClient(raw_provider, already, design['max_api_requests'])
    if not provider.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not configured')
    for episode in episodes:
        existing = next((c for c in result['conditions'] if c['episode_id'] == episode['episode_id']), None)
        if existing and existing['status'] != 'partial':
            continue
        if existing is None:
            sample_episode = deepcopy(episode)
            sample_episode['task_stream'] = [t for t in episode['task_stream'] if t['release_at_ms'] == 0]
            sample = sample_parallel(provider, sample_episode, 501)
            condition = {'episode_id': episode['episode_id'], 'source_episode_id': episode['source_development_episode_id'],
                'family': episode['family_block'], 'sample': sample, 'status': 'partial', 'rows': [],
                'scores': [score(episode, t['task_id'], sample['records'].get(t['task_id'])) for t in sample_episode['task_stream']]}
            result['conditions'].append(condition)
            write(LIVE, result)
        else:
            condition = existing
        if condition['sample']['errors']:
            condition['status'] = 'early_provider_failure_preserved'
            write(LIVE, result)
            continue
        if episode['family_block'] == 'F2':
            for label in LATE_LABELS:
                if any(r['policy'] == label for r in condition['rows']):
                    continue
                row = late_run(episode, condition['sample']['records'], label, provider)
                condition['rows'].append(row)
                write(LIVE, result)
                print(json.dumps({'episode': episode['episode_id'], 'policy': label, 'late_errors': row['late_errors'],
                    'all_served': row['all_tasks_served'], 'all_deadlines': row['all_deadlines_met']}), flush=True)
        else:
            labels = FIXED + ('FixedProposalExact',) + (('ReleasedModeEnumerationExact',) if episode['family_block'] == 'F3' else ())
            for label in labels:
                if any(r['policy'] == label for r in condition['rows']):
                    continue
                if label.endswith('Exact') and not all(s['semantic_correct'] for s in condition['scores']):
                    row = {'policy': label, 'status': 'not_executed_invalid_service_proposal', 'all_tasks_served': False,
                           'all_deadlines_met': False, 'mode_authority': 'fixed_proposal' if label == 'FixedProposalExact' else 'may_choose_acceptable_mode'}
                else:
                    row = run_one(episode, condition['sample']['records'], label)
                condition['rows'].append(row)
        condition['status'] = 'completed_with_late_errors' if any(r.get('late_errors') for r in condition['rows']) else 'complete'
        write(LIVE, result)
        print(json.dumps({'episode': episode['episode_id'], 'family': condition['family'], 'status': condition['status'],
                          'scores': condition['scores'], 'policy_runs': len(condition['rows'])}), flush=True)
    result['status'] = 'complete_with_failures' if any(c['status'] != 'complete' for c in result['conditions']) else 'complete'
    write(LIVE, result)
    return result

def audit():
    design, episodes = locked()
    result = json.loads(LIVE.read_text(encoding='utf8'))
    if result['design_sha256'] != digest(DIR / 'manifest.json') or len(result['conditions']) != 6:
        raise ValueError('incomplete or mismatched pilot')
    events = [json.loads(line) for line in (LOGDIR / 'model_events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    starts = [e for e in events if e['event_type'] == 'model_call_started']
    successes = [e for e in events if e['event_type'] == 'model_call_completed']
    failures = [e for e in events if e['event_type'] == 'model_call_failed']
    if len(starts) > 26 or len(starts) != len(successes) + len(failures):
        raise ValueError('budget exceeded or request logs incomplete')
    all_scores = []
    for condition in result['conditions']:
        episode = next(e for e in episodes if e['episode_id'] == condition['episode_id'])
        all_scores.extend(condition['scores'])
        for record in condition['sample']['records'].values():
            assert_agent_decision(record['decision'])
            visible_ids = {t['task_id'] for t in record['request']['state']['coordination_context']['requests']}
            expected = {t['task_id'] for t in episode['task_stream'] if t['release_at_ms'] == 0}
            if visible_ids != expected:
                raise ValueError('early context contains future task')
            if any(key in record['request']['task'] for key in ('required_action', 'acceptable_actions', 'action_template')):
                raise ValueError('hidden scoring leaked')
        for row in condition['rows']:
            if condition['family'] == 'F2':
                all_scores.extend(row['scores'])
                for audit_row in row['late_request_audits']:
                    if not audit_row['request_matches_runtime'] and not row['late_errors']:
                        raise ValueError('late input not bound to runtime')
                for record in row['late_records'].values():
                    if any(key in record['request']['task'] for key in ('required_action', 'acceptable_actions', 'action_template')):
                        raise ValueError('late hidden scoring leaked')
            else:
                if 'actual_proposal_latencies_ms' in row and row['model_latency_by_task_ms'] != row['actual_proposal_latencies_ms']:
                    raise ValueError('parallel proposal latencies overwritten')
    summaries = []
    for family in ('F1', 'F2', 'F3'):
        selected = [c for c in result['conditions'] if c['family'] == family]
        labels = sorted({r['policy'] for c in selected for r in c['rows']})
        for label in labels:
            rows = [r for c in selected for r in c['rows'] if r['policy'] == label]
            summaries.append({'family': family, 'policy': label, 'conditions': len(selected), 'evaluated_rows': len(rows),
                'all_served': sum(r['all_tasks_served'] for r in rows), 'all_deadlines': sum(r['all_deadlines_met'] for r in rows)})
    audited = {'status': 'audited_development_model_pilot', 'source_sha256': digest(LIVE), 'api_attempts': len(starts),
        'api_successes': len(successes), 'api_failures': len(failures), 'semantic_correct_unique_requests': sum(s['semantic_correct'] for s in all_scores),
        'policy_runs': sum(len(c['rows']) for c in result['conditions']), 'test_episodes_run': 0, 'summaries': summaries,
        'input_tokens': sum(e.get('input_tokens') or 0 for e in successes + failures),
        'output_tokens': sum(e.get('output_tokens') or 0 for e in successes + failures),
        'limits': 'one development structure per family; one sample per capacity; single model; early proposal reuse; fresh branch-specific late calls; not complete architecture/model ranking'}
    write(ROOT / 'results' / 'development_model_audit_20260930.json', audited)
    return audited

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'live', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'live': live, 'audit': audit}[stage]()
    print(json.dumps({k: v for k, v in result.items() if k not in ('conditions',)}, ensure_ascii=False))
