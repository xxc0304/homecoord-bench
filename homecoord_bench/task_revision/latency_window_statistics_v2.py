"""Post-execution metadata-only correction; no new simulation or API.

Original grid, predictions, lock, traces and failed v1 entry remain unchanged.
36 nonzero-versus-zero contrasts = 44 configs - 8 baselines; 72 arm contrasts.
Not a new preregistration or an independent acceptance.
"""
import json
import sys
from homecoord_bench.task_revision import latency_window_pilot_v1 as base
from homecoord_bench.task_revision.latency_window_pilot_v1 import (
    ROOT, OUT, old, read, sha, check, config_path, world_for, input_for,
    all_slot_common, task_delta, scalar_delta,
)
PLAN = OUT + '/plan_v2_metadata.json'
LOCK = base.LOCK
CORRECTION = 'docs/LATENCY_WINDOW_PILOT_V2_METADATA_CORRECTION_2026-10-06.md'
CORRECTED_CODE = 'homecoord_bench/task_revision/latency_window_statistics_v2.py'
CORRECTED_CROSS = 'homecoord_bench/task_revision/latency_window_crosscheck_v2.py'
CORRECTED_TEST = 'homecoord_bench/tests/test_latency_window_statistics_v2.py'
LOCK2 = OUT + '/metadata_correction_lock_v2.json'


def corrected_plan():
    value = base.read(base.PLAN)
    value['scope']['delay_contrasts'] = 36
    value['scope']['delay_arm_contrasts'] = 72
    value['metadata_revision'] = 2
    value['status'] = 'post_execution_count_correction_grid_predictions_unchanged'
    value['original_plan_sha256'] = sha(base.PLAN)
    return value


def make_correction_lock():
    base.verify_lock()
    check(not (ROOT / LOCK2).exists(), 'do not overwrite correction lock')
    check(read(PLAN) == corrected_plan(), 'amended metadata differs')
    check(not (ROOT / OUT / 'statistics.json').exists(), 'summary already generated')
    files = [PLAN, CORRECTION, CORRECTED_CODE, CORRECTED_CROSS, CORRECTED_TEST,
             base.PLAN, base.LOCK, base.GATE, OUT + '/statistics_preflight_failure_v1.json',
             *[config_path(i) for i in range(44)],
             *[OUT + '/diagnostic_world_' + str(n).zfill(2) + '.json' for n in (1, 3, 5, 7)]]
    return {'status': 'author_post_execution_metadata_correction_not_new_preregistration',
            'sha256': {p: sha(p) for p in files},
            'scope': read(PLAN)['scope'], 'original_grid_and_predictions_unchanged': True,
            'new_performance_runs': 0, 'independent_acceptance': None}


def verify_lock():
    original = base.verify_lock()
    amended = read(LOCK2)
    for p, h in amended['sha256'].items():
        check(sha(p) == h, 'metadata correction source changed: ' + p)
    check(read(PLAN) == corrected_plan(), 'corrected metadata changed')
    return original


def build_statistics():
    lock = verify_lock()
    plan = read(PLAN)
    docs = [read(config_path(i)) for i in range(44)]
    for c, d in zip(plan['configurations'], docs):
        check(d['config'] == c and d['world'] == world_for(c), 'config/world binding')
        check(d['input'] == input_for(d['world']) and d['lock_sha256'] == sha(LOCK), 'input/lock binding')
        check(d['pair'] == old.pair_audit(d['input'], d['runs']), 'stored pair mismatch')
    worlds, delay_contrasts, adjacent = [], [], []
    for w in plan['worlds']:
        entries = [d for d in docs if d['world']['world_id'] == w['world_id']]
        entries.sort(key=lambda d: d['config']['review_delay_ms'])
        # Pure d intervention: all public calls and pre-review execution equal.
        def prefix(run):
            es = run['trace']['events']
            j = next(i for i, x in enumerate(es) if x['type'] == 'reservation_review_started')
            return es[:j]
        for arm_index in (0, 1):
            base = entries[0]['runs'][arm_index]
            for d in entries:
                check(base['calls'] == d['runs'][arm_index]['calls'] and
                      prefix(base) == prefix(d['runs'][arm_index]), 'delay changed proposal/input prefix')
        audits = [a for d in entries for a in d['pair']['audits']]
        common = all_slot_common(audits)
        worlds.append({'world_id': w['world_id'], 'template': w['template'],
                       'capacity_arm': w['capacity_arm'], 'arrival_regime': w['arrival_regime'],
                       'all_delay_inputs_and_pre_review_prefix_equal': True,
                       'all_planned_slots_common_K_time': common,
                       'slots': [{'config_id': d['config']['config_id'],
                                  'review_delay_ms': d['config']['review_delay_ms'],
                                  'prediction_matches': d['prediction_matches'],
                                  'pair': d['pair']} for d in entries]})
        for d in entries[1:]:
            delay_contrasts.append({'world_id': w['world_id'], 'left_config_id': entries[0]['config']['config_id'],
                                   'right_config_id': d['config']['config_id'], 'direction': 'high_minus_zero',
                                   'delta_review_ms': d['config']['review_delay_ms'],
                                   'by_arm': {arm: task_delta(entries[0]['pair']['audits'][j], d['pair']['audits'][j])
                                              for j, arm in enumerate(old.ARMS)},
                                   'scalar_by_arm': {arm: scalar_delta(entries[0]['pair']['audits'][j], d['pair']['audits'][j])
                                                     for j, arm in enumerate(old.ARMS)},
                                   'world_common_K_coverage': common['coverage']})
        for a, b in zip(entries, entries[1:]):
            delta_d = b['config']['review_delay_ms'] - a['config']['review_delay_ms']
            changes = {arm: task_delta(a['pair']['audits'][j], b['pair']['audits'][j])
                       for j, arm in enumerate(old.ARMS)}
            adjacent.append({'world_id': w['world_id'], 'left_delay_ms': a['config']['review_delay_ms'],
                             'right_delay_ms': b['config']['review_delay_ms'], 'delta_review_ms': delta_d,
                             'by_arm': changes,
                             'scalar_by_arm': {arm: scalar_delta(a['pair']['audits'][j], b['pair']['audits'][j])
                                               for j, arm in enumerate(old.ARMS)},
                             'world_common_K_coverage': common['coverage'],
                             'water_finite_difference_factor': {
                                 arm: changes[arm]['water']['completion_latency_ms'] / delta_d
                                 if changes[arm]['water']['completion_latency_ms'] is not None else None
                                 for arm in old.ARMS}})
    diagnostics = {'records': [r for n in (1, 3, 5, 7)
                              for r in read(OUT + '/diagnostic_world_' + str(n).zfill(2) + '.json')['records']]}
    check(len(delay_contrasts) == 36 and len(adjacent) == 36 and len(diagnostics['records']) == 24, 'statistics scope')
    return {'status': 'author_recount_metadata_revision2_not_independent_review', 'metadata_revision': 2, 'metadata_correction_lock_sha256': sha(LOCK2), 'scope': plan['scope'],
            'prediction_matches': sum(d['prediction_matches'] for d in docs), 'predictions_total': 44,
            'worlds': worlds, 'delay_contrasts': delay_contrasts, 'adjacent_delay_contrasts': adjacent,
            'protected_hashes_matched': len(lock['protected_sha256']),
            'raw_artifact_sha256': {config_path(i): sha(config_path(i)) for i in range(44)},
            'plan_sha256': sha(PLAN), 'lock_sha256': sha(LOCK),
            'api_calls': 0, 'holdout_read': False, 'independent_acceptance': None,
            'novelty_proved': False, 'deployment_latency_measured': False, 'rankings': False}


if __name__ == '__main__':
    cmd = sys.argv[1]
    result = corrected_plan() if cmd == 'plan' else make_correction_lock() if cmd == 'lock' else build_statistics() if cmd == 'statistics' else None
    check(result is not None, 'unknown command')
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))
