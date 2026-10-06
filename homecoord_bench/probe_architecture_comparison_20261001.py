"""Locked, bounded three-arm pilot. Offline and real outputs stay separate."""
import argparse
import json
from statistics import median
from copy import deepcopy
from pathlib import Path

from build_task_family_split_20260930 import locked_development, DIR as SPLIT_DIR
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_multimode_20260930 import PublicModeClient
from runtime.architecture_comparison import (
    ARMS, POLICY, ComparisonReleaseProvider, SavedComparisonProvider, BudgetedClient, RequestBudget)
from runtime.central_batch import CentralBatchDeepSeekClient
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from evaluate import task_accepts_action

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20261001_architecture_comparison'
PREREG = ROOT.parent / 'docs' / 'ARCHITECTURE_COMPARISON_PREREG_2026-10-01.md'


def implementation_hashes():
    paths = sorted(ROOT.glob('*.py')) + sorted((ROOT / 'runtime').glob('*.py'))
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def prepare():
    if (DIR / 'manifest.json').exists():
        raise ValueError('protocol already locked; refusing overwrite')
    _, episodes = locked_development()
    selected = [e for e in episodes if e['pairing']['temporal_arm'] ==
                ('late' if e['family_block'] == 'F2' else 'base')]
    selected.sort(key=lambda e: e['episode_id'])
    if len(selected) != 12:
        raise ValueError('expected six development structures with two capacity controls')
    hashes, units = {}, []
    for index, source in enumerate(selected):
        episode = deepcopy(source)
        episode['source_development_episode_id'] = source['episode_id']
        episode['episode_id'] = episode['base_episode_id'] = f'HC-ARCH-{index + 1:02d}'
        path = DIR / (episode['episode_id'] + '.json')
        write(path, episode)
        hashes[path.name] = digest(path)
        for repetition in (1, 2):
            shift = (index + repetition - 1) % len(ARMS)
            for arm in ARMS[shift:] + ARMS[:shift]:
                calls = (len({t['release_at_ms'] for t in episode['task_stream']})
                         if arm == 'central_batch' else len(episode['task_stream']))
                units.append({'unit_id': f'U{index + 1:02d}-R{repetition}-{arm}',
                              'filename': path.name, 'arm': arm,
                              'repetition': repetition, 'max_calls': calls})
    by_arm = {a: sum(u['max_calls'] for u in units if u['arm'] == a) for a in ARMS}
    manifest = {'status': 'locked_before_new_model_calls', 'model': 'deepseek-flash',
                'reasoning_effort': 'none', 'max_attempts': 1, 'timeout_seconds': 45,
                'output_tokens_per_task': 1200, 'policy': POLICY, 'repetitions': 2,
                'development_conditions': 12, 'development_structures': 6,
                'max_api_requests': sum(by_arm.values()), 'calls_by_arm': by_arm,
                'max_policy_runs': len(units), 'test_episodes_run': 0,
                'candidate_sha256': hashes, 'units': units,
                'prereg_sha256': digest(PREREG),
                'source_split_manifest_sha256': digest(SPLIT_DIR / 'manifest.json'),
                'implementation_sha256': implementation_hashes()}
    if manifest['max_api_requests'] != 224 or len(units) != 72:
        raise ValueError('protocol request/run count mismatch')
    write(DIR / 'manifest.json', manifest)
    return manifest


def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    if (digest(PREREG) != design['prereg_sha256']
            or digest(SPLIT_DIR / 'manifest.json') != design['source_split_manifest_sha256']
            or implementation_hashes() != design['implementation_sha256']):
        raise ValueError('locked protocol/source changed; do not silently rerun')
    episodes = {}
    for filename, expected in design['candidate_sha256'].items():
        if digest(DIR / filename) != expected:
            raise ValueError('locked development input changed')
        episode = json.loads((DIR / filename).read_text(encoding='utf8'))
        if episode['split'] != 'development':
            raise ValueError('test input forbidden')
        episodes[filename] = episode
    return design, episodes


def paths(mode):
    return (ROOT / 'results' / f'architecture_comparison_{mode}_20261001.json',
            ROOT / 'runs' / f'architecture-comparison-{mode}-20261001' / 'model_events.jsonl')


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()] if path.exists() else []


def scripted_transport(payload, _headers, _timeout):
    """Synthetic API-shaped response, not a network or token-cost observation."""
    request = json.loads(payload['input'])
    if 'task_requests' in request:
        decision = {'task_decisions': [
            {'task_id': child['task']['task_id'],
             'decision': PublicModeClient('prepare', {child['task']['task_id']: 1000}).decide(child)}
            for child in request['task_requests']]}
    else:
        decision = PublicModeClient('prepare', {request['task']['task_id']: 1000}).decide(request)
    return {'id': 'scripted-not-api', 'model': 'scripted-not-a-model-observation',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(decision)}]}]}


def metrics(trace, result, records, episode):
    scores = []
    for task in episode['task_stream']:
        record = records[task['task_id']]
        actions = record['decision']['actions']
        correct = (not record['local_failure_placeholder'] and len(actions) == 1
                   and task_accepts_action(actions[0], task))
        scores.append({'task_id': task['task_id'], 'proposal_valid': not record['local_failure_placeholder'],
                       'service_choice_correct': correct, 'error': record['error']})
    completions = [e['timestamp_ms'] for e in trace['events'] if e['type'] == 'action_completed']
    return {'scores': scores, 'all_tasks_served': all(result['task_service'].values()),
            'all_deadlines_met': result['all_deadlines_met'],
            'task_service': result['task_service'], 'task_deadline_met': result['task_deadline_met'],
            'task_start_wait_ms': result['task_start_wait_ms'],
            'task_completion_latency_ms': result['task_completion_latency_ms'],
            'task_tardiness_ms': result['task_completion_tardiness_ms'],
            'first_action_start_latency_ms': result['first_action_start_latency_ms'],
            'last_actual_completion_ms': max(completions, default=None),
            'model_latency_by_task_ms': result['model_latency_by_task_ms'],
            'process_violation_ms': result['state_constraint_violation_duration_ms']}


def execute(mode):
    design, episodes = locked()
    output, log_path = paths(mode)
    report = json.loads(output.read_text(encoding='utf8')) if output.exists() else {
        'status': 'partial', 'mode': mode, 'manifest_sha256': digest(DIR / 'manifest.json'),
        'units': [], 'test_episodes_run': 0}
    if report['manifest_sha256'] != digest(DIR / 'manifest.json') or report['mode'] != mode:
        raise ValueError('existing result design mismatch')
    if any(u['status'] == 'running' for u in report['units']):
        raise RuntimeError('interrupted unit preserved; refusing automatic resampling; audit logs first')
    logger = EventLogger(log_path, f'architecture-comparison-{mode}-20261001')
    kwargs = {'model': design['model'], 'reasoning_effort': design['reasoning_effort'],
              'max_attempts': 1, 'timeout_seconds': design['timeout_seconds'], 'logger': logger}
    if mode == 'offline':
        kwargs.update(api_key='offline-placeholder', transport=scripted_transport)
    central, functional = CentralBatchDeepSeekClient(**kwargs), DeepSeekResponsesClient(**kwargs)
    if mode == 'live' and not central.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not configured; no API request sent')
    if mode == 'offline':
        central.scripted_latency_ms = functional.scripted_latency_ms = 1000
    events = read_events(log_path)
    prior = [e['request_id'] for e in events if e['event_type'] == 'architecture_call_reserved']
    if len(set(prior)) != len(prior):
        raise ValueError('duplicate call reservations in log')
    starts = [e['request_id'] for e in events if e['event_type'] == 'model_call_started']
    if not set(starts) <= set(prior):
        raise ValueError('unreserved provider attempts in log')
    known_units = {u['unit_id'] for u in report['units']}
    if any(not any(r.startswith(uid + ':') for uid in known_units) for r in prior):
        raise ValueError('orphan reservation; refusing implicit resampling')
    budget = RequestBudget(design['max_api_requests'], logger, prior)
    providers = {a: BudgetedClient(central if a == 'central_batch' else functional, budget) for a in ARMS}
    for unit in design['units']:
        existing = next((r for r in report['units'] if r['unit_id'] == unit['unit_id']), None)
        if existing:
            continue
        episode = episodes[unit['filename']]
        row = {**unit, 'status': 'running', 'family': episode['family_block'],
               'source_episode_id': episode['source_development_episode_id']}
        report['units'].append(row)
        write(output, report)  # Intent is durable before the first request.
        adapter = ComparisonReleaseProvider(unit['arm'], providers[unit['arm']], unit['unit_id'])
        trace, result = run_event_simulation(deepcopy(episode), adapter, POLICY, '', shared_safety_gate=True)
        adapter.assert_consumed()
        row.update(metrics(trace, result, adapter.records, episode))
        row.update(records=adapter.records, batches=adapter.batches, trace=trace,
                   status='complete_with_task_failures' if any(r['error'] for r in adapter.records.values()) else 'complete')
        write(output, report)
        print(json.dumps({'unit': unit['unit_id'], 'mode': mode, 'served': row['all_tasks_served'],
                          'on_time': row['all_deadlines_met'], 'status': row['status']}, ensure_ascii=False), flush=True)
    report['status'] = 'complete_with_failures' if any(r['status'] != 'complete' for r in report['units']) else 'complete'
    write(output, report)
    return report


def audit(mode):
    design, episodes = locked()
    output, log_path = paths(mode)
    report = json.loads(output.read_text(encoding='utf8'))
    if report['manifest_sha256'] != digest(DIR / 'manifest.json') or report['mode'] != mode:
        raise ValueError('result design mismatch')
    if len(report['units']) != len(design['units']) or any(r['status'] == 'running' for r in report['units']):
        raise ValueError('incomplete pilot; cannot claim full denominator')
    if report['test_episodes_run'] != 0:
        raise ValueError('test exposure forbidden')
    events = read_events(log_path)
    reserved = [e for e in events if e['event_type'] == 'architecture_call_reserved']
    starts = [e for e in events if e['event_type'] == 'model_call_started']
    ended = [e for e in events if e['event_type'] in ('model_call_completed', 'model_call_failed')]
    ids = [e['request_id'] for e in reserved]
    if (len(ids) != len(set(ids)) or len(ids) > design['max_api_requests']
            or sorted(ids) != sorted(e['request_id'] for e in starts)
            or sorted(ids) != sorted(e['request_id'] for e in ended)
            or any(e['attempt'] != 1 for e in starts)):
        raise ValueError('budget/log terminal-event mismatch')
    planned = {u['unit_id']: u for u in design['units']}
    if len({r['unit_id'] for r in report['units']}) != len(planned):
        raise ValueError('duplicate or missing execution units')
    summaries = []
    for row in report['units']:
        unit = planned[row['unit_id']]
        if any(row[k] != unit[k] for k in ('filename', 'arm', 'repetition', 'max_calls')):
            raise ValueError('unit metadata changed')
        episode = episodes[unit['filename']]
        by_task = {t['task_id']: t for t in episode['task_stream']}
        if set(row['records']) != set(by_task):
            raise ValueError('failed task omitted from denominator')
        if sum(len(b['calls']) for b in row['batches']) != unit['max_calls']:
            raise ValueError('incorrect per-unit call count')
        for batch in row['batches']:
            expected = {t['task_id'] for t in by_task.values() if t['release_at_ms'] == batch['at_ms']}
            views = batch['release_group_views']
            if {v['task']['task_id'] for v in views} != expected:
                raise ValueError('incorrect release group')
            for view in views:
                public_ids = {r['task_id'] for r in view['state']['coordination_context']['requests']}
                if public_ids != {tid for tid, t in by_task.items() if t['release_at_ms'] <= batch['at_ms']}:
                    raise ValueError('future leak or missing public released context')
                if any(k in view['task'] for k in ('required_action', 'acceptable_actions', 'action_template')):
                    raise ValueError('scoring leaked')
            for call in batch['calls']:
                request = call['request']
                if unit['arm'] == 'central_batch' and request['task_requests'] != views:
                    raise ValueError('central information mismatch')
                if unit['arm'] == 'functional_pooled' and request['release_group_views'] != views:
                    raise ValueError('pooled information mismatch')
                if unit['arm'] == 'functional_local' and 'release_group_views' in request:
                    raise ValueError('local arm accidentally pooled')
        replay = SavedComparisonProvider(row)
        replay_trace, replay_result = run_event_simulation(deepcopy(episode), replay, POLICY, '', shared_safety_gate=True)
        replay.assert_consumed()
        if replay_trace != row['trace']:
            raise ValueError('independent recorded-proposal replay changed execution trace')
        recomputed = metrics(replay_trace, replay_result, row['records'], episode)
        if any(row[k] != value for k, value in recomputed.items()):
            raise ValueError('saved metric mismatch')
    if mode == 'offline':
        fields = ('task_service', 'all_deadlines_met', 'task_start_wait_ms',
                  'task_completion_latency_ms', 'model_latency_by_task_ms', 'process_violation_ms')
        for filename in episodes:
            for rep in (1, 2):
                group = [r for r in report['units'] if r['filename'] == filename and r['repetition'] == rep]
                if len(group) != 3 or any(any(r[f] != group[0][f] for f in fields) for r in group):
                    raise ValueError('scripted action/latency identity control failed')
    for arm in ARMS:
        rows = [r for r in report['units'] if r['arm'] == arm]
        arm_ends = [e for e in ended if any(e['request_id'].startswith(r['unit_id'] + ':') for r in rows)]
        per_family = []
        for family in ('F1', 'F2', 'F3'):
            for resource in ('competition', 'no_competition'):
                subset = [r for r in rows if r['family'] == family and
                          episodes[r['filename']]['pairing']['resource_arm'] == resource]
                per_family.append({'family': family, 'resource_arm': resource, 'units': len(subset),
                                   'all_served': sum(r['all_tasks_served'] for r in subset),
                                   'all_on_time': sum(r['all_deadlines_met'] for r in subset)})
        call_durations = [c['call_duration_ms'] for r in rows for b in r['batches'] for c in b['calls']]
        summaries.append({'arm': arm, 'execution_units': len(rows),
                          'all_served': sum(r['all_tasks_served'] for r in rows),
                          'all_on_time': sum(r['all_deadlines_met'] for r in rows),
                          'tasks': sum(len(r['scores']) for r in rows),
                          'invalid_task_proposals': sum(not s['proposal_valid'] for r in rows for s in r['scores']),
                          'service_choice_correct': sum(s['service_choice_correct'] for r in rows for s in r['scores']),
                          'api_requests' if mode == 'live' else 'scripted_requests': len(arm_ends),
                          'provider_or_protocol_failures': sum(e['event_type'] == 'model_call_failed' for e in arm_ends),
                          'returned_models': sorted({e.get('model', 'unknown') for e in arm_ends}),
                          'measured_call_duration_ms': {'count': len(call_durations),
                              'min': min(call_durations), 'median': median(call_durations), 'max': max(call_durations)},
                          'by_family_and_resource': per_family,
                          'input_tokens_reported': sum(e.get('input_tokens') or 0 for e in arm_ends),
                          'output_tokens_reported': sum(e.get('output_tokens') or 0 for e in arm_ends),
                          'usage_missing_calls': sum(e.get('input_tokens') is None or e.get('output_tokens') is None for e in arm_ends)})
    result = {'status': 'audited_' + mode + '_architecture_pilot', 'source_sha256': digest(output),
              'test_episodes_run': 0, 'execution_units': len(report['units']),
              'new_api_requests': len(starts) if mode == 'live' else 0,
              'scripted_requests': len(starts) if mode == 'offline' else 0,
              'summaries': summaries,
              'limits': 'six author-defined development structures; two repetitions; common EDF; no deployment or held-out evidence'}
    write(ROOT / 'results' / f'architecture_comparison_{mode}_audit_20261001.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'offline', 'live', 'audit'))
    parser.add_argument('--mode', choices=('offline', 'live'), default='offline')
    args = parser.parse_args()
    result = prepare() if args.stage == 'prepare' else audit(args.mode) if args.stage == 'audit' else execute(args.stage)
    print(json.dumps({k: v for k, v in result.items() if k not in ('units', 'candidate_sha256', 'implementation_sha256')}, ensure_ascii=False))
