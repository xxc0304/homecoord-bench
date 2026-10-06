"""Separate raw-event arithmetic crosscheck. Same author, not independent review.

No generator, engine, author scorer or simulation is imported. The conditional
physical lower bound is supplementary post-run interpretation, not a planned
primary score or an offline/online optimum.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = 'docs/f2_reservation_ablation_v1_20261005'


def read(path): return json.loads((ROOT / path).read_text(encoding='utf-8'))


def check(ok, message):
    if not ok: raise ValueError(message)


def sha(path): return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def summary(e, run):
    tasks = {t['task_id']: t for t in e['task_stream']}
    starts, finishes, intervals = {}, {}, []
    for i, x in enumerate(run['trace']['events']):
        if x['type'] == 'action_started':
            tid = x['task_id']; check(tid not in starts, 'duplicate start')
            check(x['timestamp_ms'] >= tasks[tid]['release_at_ms'] + 300 + 100, 'early start')
            starts[tid] = (x, i)
        if x['type'] == 'action_completed':
            tid = x['task_id']; check(tid in starts and tid not in finishes, 'unmatched receipt')
            s, si = starts[tid]
            check(all(s[k] == x[k] for k in ('agent_id', 'target', 'operation', 'proposal_id', 'reservation_generation')), 'wrong receipt')
            check(x['timestamp_ms'] - s['timestamp_ms'] == s['duration_ms'], 'incorrect duration')
            finishes[tid] = (x, i)
            intervals.append((s['timestamp_ms'], x['timestamp_ms'], s['power_kw']))
    bounds = sorted({v for a, b, _ in intervals for v in (a, b)})
    check(all(sum(u for a, b, u in intervals if a <= left < b) <= e['home']['resources']['max_power_kw']
              for left in bounds), 'resource violation')
    result = {}
    for tid, t in tasks.items():
        S = starts[tid][0]['timestamp_ms'] if tid in starts else None
        F = finishes[tid][0]['timestamp_ms'] if tid in finishes else None
        result[tid] = {'start_ms': S, 'completion_ms': F, 'completed': F is not None,
                       'timely': F is not None and F <= t['completion_deadline_ms'],
                       'task_start_wait_ms': S-t['release_at_ms'] if S is not None else None,
                       'completion_latency_ms': F-t['release_at_ms'] if F is not None else None,
                       'execution_ms': F-S if F is not None else None,
                       'tardiness_ms': max(0, F-t['completion_deadline_ms']) if F is not None else None}
    return result


def bound_from_commit(e, commit):
    now = commit['timestamp_ms']; ready = now + e['simulation']['command_latency_ms']
    water = next(g for g in e['action_grounding'] if g['task_id'] == 'water' and g['operation'] == 'prepare')
    physical = [(c['timestamp_ms'], c['timestamp_ms']+c['duration_ms'], c['power_kw']) for c in commit['running_actions']]
    candidates = sorted({ready, *(end for _, end, _ in physical if end >= ready)})
    capacity = e['home']['resources']['max_power_kw']
    for start in candidates:
        end = start + water['duration_ms']
        points = {start, *(b for _, b, _ in physical if start <= b < end)}
        if all(water['power_kw'] + sum(u for a, b, u in physical if a <= t < b) <= capacity for t in points):
            return {'earliest_start_ms_ignoring_unstarted_reservations': start,
                    'earliest_finish_ms_for_same_running_prefix': end,
                    'interpretation': 'conditional_on_actual_prefix_and_common_command_floor_not_unavoidable_online_loss',
                    'post_run_supplementary_not_preregistered_primary_metric': True}
    raise ValueError('no start found after physical completions')


def build():
    plan = read(OUT + '/plan.json'); statistics = read(OUT + '/statistics.json')
    lock_path = OUT + '/preregistration_lock_revision3.json'; lock = read(lock_path)
    for section in ('new_design_code_sha256', 'protected_sha256'):
        for p, digest in lock[section].items(): check(sha(p) == digest, 'hash changed: ' + p)
    for p, digest in statistics['raw_artifact_sha256'].items(): check(sha(p) == digest, 'raw artifact hash')
    config_checks = []
    for i, config in enumerate(plan['configurations']):
        d = read(OUT + '/config_' + str(i).zfill(2) + '.json'); e = d['input']
        check(d['config'] == config and d['lock_sha256'] == sha(lock_path), 'config/lock identity')
        computed = [summary(e, r) for r in d['runs']]
        check([r['arm'] for r in d['runs']] == ['retain', 'replan'], 'arm scope')
        check(d['runs'][0]['calls'] == d['runs'][1]['calls'], 'full calls differ')
        for computed_arm, saved in zip(computed, d['pair']['audits']):
            for tid, values in computed_arm.items():
                check(all(saved['tasks'][tid][k] == v for k, v in values.items()), 'event arithmetic mismatch')
            check(saved['denominators'] == {'required': 4, 'completed': sum(v['completed'] for v in computed_arm.values()),
                                          'timely': sum(v['timely'] for v in computed_arm.values())}, 'fixed E mismatch')
        for tid in computed[0]:
            for metric in ('start_ms', 'completion_ms', 'task_start_wait_ms', 'completion_latency_ms', 'execution_ms', 'tardiness_ms'):
                a, b = computed[0][tid][metric], computed[1][tid][metric]
                expected = b-a if a is not None and b is not None else None
                check(d['pair']['per_task_deltas'][tid][metric] == expected, 'task delta mismatch')
        events = [r['trace']['events'] for r in d['runs']]
        indices = [next(j for j, x in enumerate(es) if x['type'] == 'reservation_review_committed') for es in events]
        check(events[0][:indices[0]+1] == events[1][:indices[1]+1], 'intervention prefix differs')
        commit = events[0][indices[0]]
        bound = bound_from_commit(e, commit)
        config_checks.append({'config_id': config['config_id'], 'two_arm_raw_arithmetic_equal': True,
                              'full_inputs_and_prefix_equal': True, 'commit_event_indices': indices,
                              'physical_prefix_bound': bound,
                              'replan_water_attains_this_conditional_bound': computed[1]['water']['start_ms'] == bound['earliest_start_ms_ignoring_unstarted_reservations']})
        check(statistics['configurations'][i]['pair'] == d['pair'], 'summary binding')
    for i in range(4):
        diag = read(OUT + '/diagnostic_' + str(i).zfill(2) + '.json')
        main = read(OUT + '/config_' + str(i*2).zfill(2) + '.json')
        for r in diag['records']:
            original = next(m for m in main['runs'] if m['arm'] == r['arm']); cutoff = r['cutoff_ms']
            for channel in ('calls', 'events'):
                def prefix(run):
                    if channel == 'calls': return [c for c in run['calls'] if c['request']['current_time_ms'] < cutoff]
                    return [x for x in run['trace']['events'] if x['timestamp_ms'] < cutoff]
                check(prefix(original) == prefix(r['run']), 'future information in prefix')
    return {'status': 'same_author_separate_algorithm_crosscheck_passed_not_independent_acceptance',
            'scope': {'physical_runs': 16, 'pairs': 8, 'information_diagnostics': 24},
            'configurations': config_checks, 'protected_hashes_checked': len(lock['protected_sha256']),
            'statistics_sha256': sha(OUT + '/statistics.json'), 'api_calls': 0, 'new_simulator_runs': 0,
            'independent_review': None}


if __name__ == '__main__': print(json.dumps(build(), ensure_ascii=True, separators=(',', ':')))
