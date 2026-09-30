"""Calibrate ordinary dispatch/retry callbacks then paired serialized-worker replay."""
import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from statistics import median
from probe_c3_action_choice_20260930 import write, digest
from probe_c3_multimode_replication_20260930 import locked as source_locked, LIVE, build, records_for
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_c3_ordinary_compute'
CALIBRATION = ROOT / 'results' / 'c3_ordinary_compute_calibration_20260930.json'
OUTPUT = ROOT / 'results' / 'c3_ordinary_compute_20260930.json'
PREREG = ROOT.parent / 'docs' / 'C3_ORDINARY_COMPUTE_PREREG_2026-09-30.md'
POLICIES = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')

def execute(episode, records, policy, *, profile=None, measure=False, update=None):
    changed = deepcopy(episode)
    changed['simulation']['measure_coordination_compute'] = measure
    if profile is not None:
        changed['simulation']['coordination_compute_profile'] = profile
    if update is not None:
        changed['exogenous_events'].append(update)
    client = MemoryReplayClient(deepcopy(release_order_records(changed, records)))
    trace, result = run_event_simulation(changed, client, policy, '', shared_safety_gate=True)
    client.assert_consumed()
    if result['model_latency_by_task_ms'] != {tid: r['logical_latency_ms'] for tid, r in records.items()}:
        raise ValueError('model latency overwritten')
    events = trace['events']
    last = max((e['timestamp_ms'] for e in events if e['type'] == 'action_completed'), default=None)
    return {'policy': policy, 'compute_profile': profile, 'measurements': result['coordination_compute_measurements'],
        'all_tasks_served': all(result['task_service'].values()), 'all_deadlines_met': result['all_deadlines_met'],
        'task_service': result['task_service'], 'task_start_wait_ms': result['task_start_wait_ms'],
        'task_completion_latency_ms': result['task_completion_latency_ms'], 'last_actual_completion_ms': last,
        'model_latency_by_task_ms': result['model_latency_by_task_ms'],
        'process_violation_ms': result['state_constraint_violation_duration_ms'],
        'retry_queued_count': result['retry_queued_count'], 'retry_scheduled_count': result['retry_scheduled_count'],
        'events': events}

def sources():
    manifest = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    if digest(LIVE) != manifest['source_sha256'] or digest(PREREG) != manifest['prereg_sha256']:
        raise ValueError('locked input changed')
    _, episodes = source_locked()
    batches = [b for b in json.loads(LIVE.read_text(encoding='utf8'))['batches'] if not b['sample']['errors']]
    return manifest, episodes, batches

def scripted():
    episode = build(3)
    records = records_for(episode, {'laundry': 'fast', 'meal': 'fast'}, {tid: 800 for tid in ('laundry', 'meal', 'water')})
    return episode, records

def prepare():
    source_locked()
    model = json.loads(LIVE.read_text(encoding='utf8'))
    manifest = {'status': 'locked_before_ordinary_compute_calibration', 'source_sha256': digest(LIVE),
        'prereg_sha256': digest(PREREG), 'calibration_runs': 48, 'paired_runs': 32, 'control_runs': 2,
        'new_api_calls': 0, 'policies': list(POLICIES), 'excluded_batches':
        [{'capacity_units': b['capacity_units'], 'repetition': b['repetition'], 'errors': b['sample']['errors']}
         for b in model['batches'] if b['sample']['errors']]}
    write(DIR / 'manifest.json', manifest)
    return manifest

def calibrate():
    sources_manifest, episodes, batches = sources()
    rows = []
    for batch in batches:
        for policy in POLICIES:
            for repeat in range(1, 4):
                row = execute(episodes[batch['capacity_units']], batch['sample']['records'], policy, measure=True)
                previous = next(r for r in batch['rows'] if r['policy'] == policy)
                for field in ('all_tasks_served', 'all_deadlines_met', 'task_start_wait_ms', 'task_completion_latency_ms',
                              'last_actual_completion_ms', 'model_latency_by_task_ms'):
                    if row[field] != previous[field]:
                        raise ValueError('profiling changed historical result: ' + field)
                row.update(capacity_units=batch['capacity_units'], batch_repetition=batch['repetition'], measurement_repeat=repeat,
                           source='recorded_model_proposals')
                rows.append(row)
    episode, records = scripted()
    for repeat in range(1, 4):
        row = execute(episode, records, 'GateRetryRule', measure=True)
        if not row['retry_scheduled_count']:
            raise ValueError('scripted calibration did not exercise retry')
        row.update(source='scripted_retry_control', measurement_repeat=repeat)
        rows.append(row)
    profiles, stats = {}, []
    for policy in POLICIES:
        profile = {}
        for stage in ('dispatch', 'retry_batch'):
            walls = [m['wall_ms'] for r in rows if r['policy'] == policy for m in r['measurements'] if m['stage'] == stage]
            profile[stage + '_ms'] = math.ceil(median(walls)) if walls else 0
            stats.append({'policy': policy, 'stage': stage, 'observations': len(walls),
                'median_wall_ms': median(walls) if walls else None, 'min_wall_ms': min(walls) if walls else None,
                'max_wall_ms': max(walls) if walls else None, 'charged_ms': profile[stage + '_ms'],
                'measurement_status': 'measured' if walls else 'not_observed'})
        profiles[policy] = profile
    if len(rows) != 48:
        raise ValueError('incorrect calibration count')
    result = {'status': 'completed_calibration', 'manifest_sha256': digest(DIR / 'manifest.json'),
              'new_api_calls': 0, 'profiles': profiles, 'stats': stats, 'rows': rows}
    write(CALIBRATION, result)
    write(DIR / 'profile_lock.json', {'status': 'locked_before_paired_replay',
        'calibration_sha256': digest(CALIBRATION), 'profiles': profiles})
    return result

def audit_jobs(row):
    starts = {e['job_id']: e for e in row['events'] if e['type'] == 'ordinary_coordination_started'}
    finishes = {e['job_id']: e for e in row['events'] if e['type'] == 'ordinary_coordination_completed'}
    queued = {e['job_id']: e for e in row['events'] if e['type'] == 'coordinator_job_queued'}
    for kind, items in (('ordinary_coordination_started', starts), ('ordinary_coordination_completed', finishes),
                        ('coordinator_job_queued', queued)):
        if len(items) != sum(e['type'] == kind for e in row['events']):
            raise ValueError('duplicate job event')
    if set(starts) != set(finishes) or set(starts) != set(queued):
        raise ValueError('missing/duplicate worker event')
    last = -1
    for job_id in sorted(starts):
        start, finish = starts[job_id], finishes[job_id]
        if start['timestamp_ms'] < last or finish['timestamp_ms'] - start['timestamp_ms'] != start['duration_ms']:
            raise ValueError('worker overlap or incorrect service duration')
        if start['timestamp_ms'] - queued[job_id]['timestamp_ms'] != queued[job_id]['worker_queue_wait_ms']:
            raise ValueError('worker wait misreported')
        last = finish['timestamp_ms']
    if sum(e['stage'] == 'dispatch' for e in starts.values()) != 3:
        raise ValueError('initial proposal counted repeatedly')
    if row['policy'] != 'GateRetryRule' and any(e['stage'] == 'retry_batch' for e in starts.values()):
        raise ValueError('unused retry charged')
    # Each reservation occurs only inside a callback at a completion clock.
    clocks = {e['timestamp_ms'] for e in finishes.values()}
    for event in row['events']:
        if event['type'] == 'action_reserved':
            if event['timestamp_ms'] not in clocks or event['scheduled_start_ms'] < event['timestamp_ms'] + 100:
                raise ValueError('reservation skipped compute or command clock')
    return {'worker_jobs': len(starts), 'retry_batch_jobs': sum(e['stage'] == 'retry_batch' for e in starts.values()),
            'charged_worker_service_ms': sum(e['duration_ms'] for e in starts.values()),
            'worker_queue_wait_ms': sum(e['worker_queue_wait_ms'] for e in queued.values())}

def run():
    manifest, episodes, batches = sources()
    lock = json.loads((DIR / 'profile_lock.json').read_text(encoding='utf8'))
    calibration = json.loads(CALIBRATION.read_text(encoding='utf8'))
    if digest(CALIBRATION) != lock['calibration_sha256'] or calibration['manifest_sha256'] != digest(DIR / 'manifest.json'):
        raise ValueError('calibration lock changed')
    pairs = []
    for batch in batches:
        for policy in POLICIES:
            zero = execute(episodes[batch['capacity_units']], batch['sample']['records'], policy)
            timed = execute(episodes[batch['capacity_units']], batch['sample']['records'], policy, profile=lock['profiles'][policy])
            audited = audit_jobs(timed)
            pair = {'capacity_units': batch['capacity_units'], 'batch_repetition': batch['repetition'], 'source': 'recorded_model_proposals',
                    'zero': zero, 'timed': timed, 'worker_audit': audited,
                    'task_wait_delta_ms': {tid: timed['task_start_wait_ms'][tid] - zero['task_start_wait_ms'][tid]
                        for tid in zero['task_start_wait_ms'] if timed['task_start_wait_ms'][tid] is not None and zero['task_start_wait_ms'][tid] is not None}}
            pairs.append(pair)
    episode, records = scripted()
    zero = execute(episode, records, 'GateRetryRule')
    timed = execute(episode, records, 'GateRetryRule', profile=lock['profiles']['GateRetryRule'])
    pairs.append({'source': 'scripted_retry_control', 'zero': zero, 'timed': timed, 'worker_audit': audit_jobs(timed)})
    delay = lock['profiles']['GateRetryRule']['dispatch_ms']
    if delay < 1:
        raise ValueError('positive profile needed for control')
    controls = []
    # Same-clock update precedes worker completion at millisecond resolution.
    for condition, patch in (('unrelated_version_change', {'diagnostics.tick': 1}),
                             ('necessary_precondition_change', {'devices.water_heater': 'busy'})):
        row = execute(episode, records, 'GateRetryRule', profile=lock['profiles']['GateRetryRule'],
                      update={'event': condition, 'at_ms': 800 + delay, 'patch': patch})
        row.update(condition=condition, worker_audit=audit_jobs(row))
        if condition == 'unrelated_version_change' and not row['all_tasks_served']:
            raise ValueError('benign version change rejects service')
        if condition == 'necessary_precondition_change' and (row['task_service']['water'] or row['task_start_wait_ms']['water'] is not None):
            raise ValueError('invalid action started')
        controls.append(row)
    summaries = []
    for policy in POLICIES:
        subset = [p for p in pairs if p['source'] == 'recorded_model_proposals' and p['zero']['policy'] == policy]
        summaries.append({'policy': policy, 'paired_batches': len(subset),
            'zero_all_deadlines': sum(p['zero']['all_deadlines_met'] for p in subset),
            'timed_all_deadlines': sum(p['timed']['all_deadlines_met'] for p in subset),
            'whole_completion_delta_ms': [p['timed']['last_actual_completion_ms'] - p['zero']['last_actual_completion_ms'] for p in subset],
            'retry_batch_jobs': sum(p['worker_audit']['retry_batch_jobs'] for p in subset)})
    result = {'status': 'audited_ordinary_calibrated_compute_replay', 'new_api_calls': 0,
        'profile_lock_sha256': digest(DIR / 'profile_lock.json'), 'calibration_runs': 48, 'paired_runs': 32, 'control_runs': 2,
        'profiles': lock['profiles'], 'stats': calibration['stats'], 'summaries': summaries, 'pairs': pairs, 'controls': controls,
        'limits': 'calibrated callback costs; development data; single FIFO worker; excludes EDF front-end, safety gate, network; not total algorithm latency ranking'}
    write(OUTPUT, result)
    return result

def audit():
    manifest, _, batches = sources()
    result = json.loads(OUTPUT.read_text(encoding='utf8'))
    calibration = json.loads(CALIBRATION.read_text(encoding='utf8'))
    lock = json.loads((DIR / 'profile_lock.json').read_text(encoding='utf8'))
    if (digest(CALIBRATION) != lock['calibration_sha256']
            or digest(DIR / 'profile_lock.json') != result['profile_lock_sha256']
            or calibration['manifest_sha256'] != digest(DIR / 'manifest.json')
            or result['profiles'] != calibration['profiles'] or lock['profiles'] != calibration['profiles']):
        raise ValueError('audit calibration/manifest/profile mismatch')
    if len(calibration['rows']) != 48 or len(result['pairs']) != 16 or len(result['controls']) != 2:
        raise ValueError('incorrect actual run counts')
    for pair in result['pairs']:
        audit_jobs(pair['timed'])
        if pair['source'] == 'recorded_model_proposals':
            previous = next(r for b in batches if b['capacity_units'] == pair['capacity_units']
                            and b['repetition'] == pair['batch_repetition'] for r in b['rows']
                            if r['policy'] == pair['zero']['policy'])
            for field in ('all_tasks_served', 'all_deadlines_met', 'task_start_wait_ms', 'task_completion_latency_ms',
                          'last_actual_completion_ms', 'model_latency_by_task_ms'):
                if pair['zero'][field] != previous[field]:
                    raise ValueError('zero replay historical result changed')
    for row in result['controls']:
        audit_jobs(row)
    audited = {'status': 'audited', 'source_sha256': digest(OUTPUT), 'new_api_calls': 0,
        'calibration_runs': 48, 'paired_runs': 32, 'control_runs': 2,
        'historical_zero_metric_checks': 15, 'profiles': result['profiles'], 'summaries': result['summaries'],
        'stats': result['stats'], 'limits': result['limits']}
    write(ROOT / 'results' / 'c3_ordinary_compute_audit_20260930.json', audited)
    return audited

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'calibrate', 'run', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'calibrate': calibrate, 'run': run, 'audit': audit}[stage]()
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'pairs', 'controls')}, ensure_ascii=False))
