"""Charge measured public-plan computation once per released batch."""
import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_multimode_20260930 import public_plan, LABELS
from probe_c3_multimode_replication_20260930 import locked as source_locked, LIVE
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_c3_compute_clock'
OUTPUT = ROOT / 'results' / 'c3_compute_clock_20260930.json'
PREREG = ROOT.parent / 'docs' / 'C3_COMPUTE_CLOCK_PREREG_2026-09-30.md'

def execute(episode, records, plan, label, compute_ms, update=None):
    changed, chosen = deepcopy(episode), deepcopy(records)
    for task in changed['task_stream']:
        action = chosen[task['task_id']]['decision']['actions'][0]
        tool = next(t for t in episode['tool_catalog'] if t['agent_id'] == task['agent_id']
                    and t['operation'] == plan['tasks'][task['task_id']]['operation'])
        if label == 'ReleasedModeEnumerationExact':
            action.update(operation=tool['operation'], target=tool['target'],
                          estimated_duration_ms=tool['cost_contract']['duration_ms'],
                          estimated_power_kw=tool['cost_contract']['resource_units'])
    changed['simulation'].update(released_batch_plan=deepcopy(plan),
        released_batch_compute_ms=compute_ms, hold_until_ms=plan['available_at_ms'])
    if update is not None:
        changed['exogenous_events'].append(deepcopy(update))
    client = MemoryReplayClient(deepcopy(release_order_records(changed, chosen)))
    trace, result = run_event_simulation(changed, client, 'FixedHoldCoordinator', '', shared_safety_gate=True)
    client.assert_consumed()
    events = trace['events']
    started = [e for e in events if e['type'] == 'coordination_started']
    finished = [e for e in events if e['type'] == 'coordination_completed']
    if len(started) != 1 or len(finished) != 1:
        raise ValueError('computation must be charged once per batch')
    if (started[0]['timestamp_ms'] != plan['available_at_ms']
            or finished[0]['timestamp_ms'] != plan['available_at_ms'] + compute_ms):
        raise ValueError('incorrect batch computation clock')
    actual = {e['task_id']: e['timestamp_ms'] for e in events if e['type'] == 'action_started'}
    expected = {tid: p['start_ms'] + compute_ms for tid, p in plan['tasks'].items()}
    if any(at != expected[tid] for tid, at in actual.items()):
        raise ValueError('command time or planned offset lost')
    if result['model_latency_by_task_ms'] != {tid: r['logical_latency_ms'] for tid, r in records.items()}:
        raise ValueError('model latency overwritten')
    completions = [e['timestamp_ms'] for e in events if e['type'] == 'action_completed']
    return {'policy': label, 'charged_compute_ms': compute_ms,
        'mode_authority': 'may_choose_acceptable_mode' if label == LABELS[-1] else 'fixed_proposal',
        'all_tasks_served': all(result['task_service'].values()), 'all_deadlines_met': result['all_deadlines_met'],
        'task_service': result['task_service'], 'task_start_wait_ms': result['task_start_wait_ms'],
        'task_completion_latency_ms': result['task_completion_latency_ms'],
        'last_actual_completion_ms': max(completions, default=None),
        'model_latency_by_task_ms': result['model_latency_by_task_ms'],
        'process_violation_ms': result['state_constraint_violation_duration_ms'], 'plan': plan,
        'clock_events': [e for e in events if e['type'] in ('coordination_started', 'coordination_completed',
            'action_precondition_recheck', 'state_update', 'action_rejected', 'action_started', 'action_completed')]}

def prepare():
    source_locked()
    model = json.loads(LIVE.read_text(encoding='utf8'))
    complete = [b for b in model['batches'] if not b['sample']['errors']]
    manifest = {'status': 'locked_before_compute_clock_measurement', 'source_sha256': digest(LIVE),
        'prereg_sha256': digest(PREREG), 'complete_batches': len(complete),
        'excluded_batches': [{'capacity_units': b['capacity_units'], 'repetition': b['repetition'],
                            'errors': b['sample']['errors']} for b in model['batches'] if b['sample']['errors']],
        'measurements': 30, 'paired_runs': 60, 'control_runs': 4, 'new_api_calls': 0}
    write(DIR / 'manifest.json', manifest)
    return manifest

def run():
    manifest = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    if digest(LIVE) != manifest['source_sha256'] or digest(PREREG) != manifest['prereg_sha256']:
        raise ValueError('locked source changed')
    _, episodes = source_locked()
    batches = [b for b in json.loads(LIVE.read_text(encoding='utf8'))['batches'] if not b['sample']['errors']]
    pairs = []
    for batch in batches:
        episode, records = episodes[batch['capacity_units']], batch['sample']['records']
        for label in LABELS[-2:]:
            for repeat in range(1, 4):
                before = perf_counter_ns()
                plan = public_plan(episode, records, label == LABELS[-1])
                wall_ms = (perf_counter_ns() - before) / 1e6
                if plan is None:
                    raise ValueError('source fixed plan infeasible')
                charged = math.ceil(wall_ms)
                zero = execute(episode, records, plan, label, 0)
                timed = execute(episode, records, plan, label, charged)
                for field in ('task_start_wait_ms', 'task_completion_latency_ms'):
                    if any(timed[field][tid] - zero[field][tid] != charged for tid in zero[field]):
                        raise ValueError('time delta does not match charged computation')
                if timed['last_actual_completion_ms'] - zero['last_actual_completion_ms'] != charged:
                    raise ValueError('makespan time delta incorrect')
                pairs.append({'capacity_units': batch['capacity_units'], 'batch_repetition': batch['repetition'],
                              'measurement_repeat': repeat, 'public_plan_wall_ms': wall_ms, 'zero': zero, 'timed': timed})
    selected = next(p for p in pairs if p['capacity_units'] == 4 and p['zero']['policy'] == LABELS[-2])
    batch = next(b for b in batches if b['capacity_units'] == 4 and b['repetition'] == selected['batch_repetition'])
    plan = selected['zero']['plan']
    delay = selected['timed']['charged_compute_ms']
    if delay < 2:
        raise ValueError('too short to locate a strictly intermediate millisecond; keep measurement, revise control explicitly')
    controls = []
    for condition, patch, at in (
            ('stable', None, None),
            ('unrelated_version_change', {'diagnostics.tick': 1}, plan['available_at_ms'] + delay // 2),
            ('precondition_changed_during_compute', {'devices.water_heater': 'busy'}, plan['available_at_ms'] + delay // 2),
            ('precondition_changed_during_command', {'devices.water_heater': 'busy'}, plan['available_at_ms'] + delay + 50)):
        update = None if patch is None else {'event': condition, 'at_ms': at, 'patch': patch}
        row = execute(episodes[4], batch['sample']['records'], plan, LABELS[-2], delay, update)
        row['condition'] = condition
        row['controlled_update'] = update
        if condition in ('stable', 'unrelated_version_change') and not row['all_tasks_served']:
            raise ValueError('benign state/version change rejected service')
        if condition.startswith('precondition_changed'):
            if row['task_service']['water'] or row['task_start_wait_ms']['water'] is not None:
                raise ValueError('invalidated action started or missing service scored zero wait')
            if not any(e['type'] == 'action_rejected' and e['task_id'] == 'water' for e in row['clock_events']):
                raise ValueError('missing invalidation rejection')
        controls.append(row)
    summaries = []
    for label in LABELS[-2:]:
        subset = [p for p in pairs if p['zero']['policy'] == label]
        walls = [p['public_plan_wall_ms'] for p in subset]
        summaries.append({'policy': label, 'measurements': len(subset), 'median_public_plan_wall_ms': median(walls),
            'min_wall_ms': min(walls), 'max_wall_ms': max(walls),
            'zero_all_deadlines': sum(p['zero']['all_deadlines_met'] for p in subset),
            'timed_all_deadlines': sum(p['timed']['all_deadlines_met'] for p in subset)})
    if len(pairs) != 30 or len(controls) != 4:
        raise ValueError('unexpected run counts')
    result = {'status': 'audited_compute_clock_paired_replay', 'new_api_calls': 0,
        'manifest_sha256': digest(DIR / 'manifest.json'), 'measurements': 30, 'paired_runs': 60, 'control_runs': 4,
        'summaries': summaries, 'pairs': pairs, 'controls': controls,
        'limits': 'one-shot released batch public-plan cost only; fixed plans shifted; not online replanning; local wall time; dependent repeats'}
    write(OUTPUT, result)
    return result

def audit():
    manifest = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    result = json.loads(OUTPUT.read_text(encoding='utf8'))
    if (digest(LIVE) != manifest['source_sha256'] or digest(PREREG) != manifest['prereg_sha256']
            or digest(DIR / 'manifest.json') != result['manifest_sha256']):
        raise ValueError('audit source changed')
    batches = json.loads(LIVE.read_text(encoding='utf8'))['batches']
    for pair in result['pairs']:
        batch = next(b for b in batches if b['capacity_units'] == pair['capacity_units']
                     and b['repetition'] == pair['batch_repetition'])
        previous = next(r for r in batch['rows'] if r['policy'] == pair['zero']['policy'])
        for field in ('all_tasks_served', 'all_deadlines_met', 'task_start_wait_ms',
                      'task_completion_latency_ms', 'last_actual_completion_ms', 'model_latency_by_task_ms'):
            if pair['zero'][field] != previous[field]:
                raise ValueError('zero compute replay changed historical metric: ' + field)
    for control in result['controls']:
        completed = next(e for e in control['clock_events'] if e['type'] == 'coordination_completed')
        expected_changed = control['condition'] in ('unrelated_version_change', 'precondition_changed_during_compute')
        if completed['state_changed_during_compute'] != expected_changed:
            raise ValueError('wrong state evolution during computation')
    audited = {'status': 'audited', 'source_sha256': digest(OUTPUT), 'new_api_calls': 0,
               'historical_zero_replay_checks': len(result['pairs']), 'matched_metric_fields': 6,
               'paired_runs': result['paired_runs'], 'control_runs': result['control_runs'],
               'summaries': result['summaries'], 'limits': result['limits']}
    write(ROOT / 'results' / 'c3_compute_clock_audit_20260930.json', audited)
    return audited

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'run', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'run': run, 'audit': audit}[stage]()
    print(json.dumps({k: v for k, v in result.items() if k not in ('pairs', 'controls')}, ensure_ascii=False))
