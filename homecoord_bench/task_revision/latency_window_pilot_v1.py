"""Development-only latency-window intervention. JSON stdout, zero API/writes.

Known boundary tests motivate this grid: not a blind test or novelty proof.
New predictions are persisted before new performance runs. Old files untouched.
"""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

from homecoord_bench.task_revision import f2_reservation_ablation_v1 as old
from homecoord_bench.task_revision.small_validation_plan_v1 import variant, differences, feasible_witness

ROOT = old.ROOT
OUT = 'docs/latency_window_pilot_v1_20261006'
PLAN = OUT + '/plan.json'
LOCK = OUT + '/author_pre_execution_lock.json'
GATE = OUT + '/baseline_gate.json'
CODE = 'homecoord_bench/task_revision/latency_window_pilot_v1.py'
CROSS = 'homecoord_bench/task_revision/latency_window_crosscheck_v1.py'
TEST = 'homecoord_bench/tests/test_latency_window_pilot_v1.py'
CONTRACT = 'docs/LATENCY_WINDOW_PILOT_V1_PREREG_2026-10-06.md'
ASSESSMENT = 'docs/LATENCY_CORE_FEASIBILITY_2026-10-06.md'
ORIGINAL_DELAYS = (0, 100, 2001)
NEAR_DELAYS = (0, 100, 1899, 1900, 1999, 2000, 2001, 3000)


def check(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def digest(obj):
    return old.object_sha(obj)


def source_rows():
    rows = [e for e in read(old.SOURCE)['episodes'] if e['pairing']['temporal_arm'] == 'late']
    check(len(rows) == 4 and all(e['split'] == 'development' for e in rows), 'development only')
    return rows


def reference(source):
    """Old data only; extract early intervals, never use old water S/F to predict."""
    candidates = read(old.PLAN)['configurations']
    item = next(c for c in candidates if c['source_episode_id'] == source['episode_id']
                and c['review_delay_ms'] == 0)
    number = candidates.index(item)
    path = old.OUT + '/config_' + str(number).zfill(2) + '.json'
    run = read(path)['runs'][0]
    check(run['arm'] == 'retain' and run['review_delay_ms'] == 0, 'reference arm')
    starts = {}
    intervals = []
    for event in run['trace']['events']:
        if event.get('task_id') == 'water':
            continue
        if event['type'] == 'action_started':
            starts[event['task_id']] = event
        if event['type'] == 'action_completed':
            s = starts[event['task_id']]
            intervals.append({'task_id': event['task_id'], 'start_ms': s['timestamp_ms'],
                              'end_ms': event['timestamp_ms'], 'units': s['power_kw']})
    check(len(intervals) == 3, 'early reference coverage')
    return path, intervals


def tight_boundary(source):
    tight = next(e for e in source_rows() if e['base_episode_id'] == source['base_episode_id']
                 and e['pairing']['resource_arm'] == 'competition')
    _, intervals = reference(tight)
    blocker = 'laundry' if source['base_episode_id'].endswith('01') else 'cleaning'
    return blocker, next(x['start_ms'] for x in intervals if x['task_id'] == blocker)


def world_episode(source, arrival):
    check(arrival in ('original', 'near_start'), 'arrival scope')
    e = deepcopy(source)
    if arrival == 'near_start':
        _, boundary = tight_boundary(source)
        release = next(t['release_at_ms'] for t in e['task_stream'] if t['task_id'] == 'water')
        e = variant(e, 'water_release_offset_ms', boundary - 300 - 2000 - release)
    delta = differences(source, e)
    allowed = {'/task_stream/3/release_at_ms', '/task_stream/3/completion_deadline_ms',
               '/exogenous_events/0/at_ms',
               '/exogenous_events/0/patch/coordination_context/requests/3/release_at_ms',
               '/exogenous_events/0/patch/coordination_context/requests/3/deadline_ms'}
    check(not delta if arrival == 'original' else set(delta) == allowed, 'input delta whitelist')
    for a, b in zip(source['task_stream'], e['task_stream']):
        check(a['completion_deadline_ms'] - a['release_at_ms'] ==
              b['completion_deadline_ms'] - b['release_at_ms'], 'own budget changed')
    return e, delta


def earliest(ready, duration, units, intervals, capacity):
    """Independent interval arithmetic; no simulator, scorer or new results."""
    for start in sorted({ready, *(x['end_ms'] for x in intervals if x['end_ms'] >= ready)}):
        end = start + duration
        points = {start, *(p for x in intervals for p in (x['start_ms'], x['end_ms'])
                          if start <= p < end)}
        if all(units + sum(x['units'] for x in intervals if x['start_ms'] <= p < x['end_ms'])
               <= capacity for p in points):
            return start
    raise ValueError('no feasible start after all locked completions')


def prediction(e, intervals, delay):
    t = next(t for t in e['task_stream'] if t['task_id'] == 'water')
    g = next(g for g in e['action_grounding'] if g['task_id'] == 'water' and g['operation'] == 'prepare')
    P = t['release_at_ms'] + 300
    C = P + delay
    running = [x for x in intervals if x['start_ms'] < C < x['end_ms']]
    future = [x for x in intervals if x['start_ms'] >= C]
    tasks = {t['task_id']: t for t in e['task_stream']}
    check(all(t['completion_deadline_ms'] < tasks[x['task_id']]['completion_deadline_ms']
              for x in future), 'water not first in remaining EDF')
    predictions = {}
    for arm, locked in [('retain', intervals), ('replan', running)]:
        S = earliest(C + e['simulation']['command_latency_ms'], g['duration_ms'],
                     g['power_kw'], locked, e['home']['resources']['max_power_kw'])
        predictions[arm] = {'start_ms': S, 'completion_ms': S + g['duration_ms']}
    return {'review_start_ms': P, 'commit_ms': C,
            'expected_running_task_ids': sorted(x['task_id'] for x in running),
            'expected_unstarted_task_ids': sorted(x['task_id'] for x in future),
            'water': predictions,
            'scope': 'conditional_on_known_early_prefix_not_general_online_optimum'}


def build_plan():
    worlds, configs = [], []
    for source in source_rows():
        path, intervals = reference(source)
        for arrival in ('original', 'near_start'):
            e, delta = world_episode(source, arrival)
            wid = 'LW1-W' + str(len(worlds)).zfill(2)
            e['episode_id'] = wid
            witness = feasible_witness(e)
            check(witness['status'] == 'constructive_schedule_found', 'world feasibility')
            blocker, B = tight_boundary(source)
            P = next(t['release_at_ms'] for t in e['task_stream'] if t['task_id'] == 'water') + 300
            world = {'world_id': wid, 'source_episode_id': source['episode_id'],
                     'source_sha256': digest(source), 'input_sha256': digest(e),
                     'template': source['base_episode_id'],
                     'capacity_arm': source['pairing']['resource_arm'], 'arrival_regime': arrival,
                     'changed_paths': delta, 'old_early_reference_path': path,
                     'early_reference_intervals': intervals, 'blocker_task_id': blocker,
                     'matched_tight_start_ms': B,
                     'matched_tight_revocation_margin_ms': B - P,
                     'matched_tight_absorption_margin_ms': B - P - 100,
                     'margin_is_active': source['pairing']['resource_arm'] == 'competition',
                     'required_task_ids': [t['task_id'] for t in e['task_stream']],
                     'feasibility': witness}
            worlds.append(world)
            costs = ORIGINAL_DELAYS if arrival == 'original' else NEAR_DELAYS
            for cost in costs:
                configs.append({'config_id': 'LW1-C' + str(len(configs)).zfill(2),
                                'world_id': wid, 'review_delay_ms': cost, 'arms': list(old.ARMS),
                                'prediction': prediction(e, intervals, cost)})
    check((len(worlds), len(configs)) == (8, 44), 'scope changed')
    return {'status': 'author_static_plan_not_independent_acceptance', 'date': '2026-10-06',
            'worlds': worlds, 'configurations': configs,
            'scope': {'worlds': 8, 'configurations': 44, 'formal_runs': 88, 'reservation_pairs': 44,
                      'delay_contrasts': 40, 'delay_arm_contrasts': 80,
                      'adjacent_delay_contrasts': 36, 'adjacent_delay_arm_contrasts': 72,
                      'information_diagnostic_runs': 24},
            'known_prior_boundary_tests': True, 'blind_test': False,
            'predictions_use_new_performance_runs': False, 'independent_structures_claimed': False,
            'api_calls': 0, 'holdout_read': False, 'rankings': False, 'p_values': False,
            'source_sha256': {old.SOURCE: sha(old.SOURCE)},
            'prediction_role': 'prospective_on_new_grid_conditional_on_known_development_prefix'}


def input_for(world):
    source = next(e for e in source_rows() if e['episode_id'] == world['source_episode_id'])
    check(digest(source) == world['source_sha256'], 'source changed')
    e, _ = world_episode(source, world['arrival_regime'])
    e['episode_id'] = world['world_id']
    check(digest(e) == world['input_sha256'], 'world changed')
    return e


def make_lock():
    check(not (ROOT / LOCK).exists(), 'do not overwrite existing lock')
    check(read(PLAN) == build_plan(), 'plan does not reproduce')
    check(not list((ROOT / OUT).glob('config_*.json')) and not (ROOT / GATE).exists(), 'execution before lock')
    new = (PLAN, CODE, CROSS, TEST, CONTRACT, ASSESSMENT)
    protected = {}
    for directory in ('docs', 'homecoord_bench/task_revision', 'homecoord_bench/tests',
                      'homecoord_bench/runtime', 'homecoord_bench/results'):
        for p in sorted((ROOT / directory).rglob('*')):
            rel = p.relative_to(ROOT).as_posix()
            if (p.is_file() and p.suffix in ('.md', '.json', '.py') and '__pycache__' not in p.parts
                    and not rel.startswith(OUT + '/') and rel not in new):
                protected[rel] = sha(rel)
    protected['homecoord_bench/evaluate.py'] = sha('homecoord_bench/evaluate.py')
    return {'status': 'author_pre_execution_lock_not_independent_freeze',
            'new_design_code_sha256': {p: sha(p) for p in new}, 'protected_sha256': protected,
            'predictions_before_new_runs': True, 'scope': read(PLAN)['scope'],
            'independent_design_acceptance': None, 'implementation_acceptance': None,
            'hashes_are_not_independent_wallclock_proof': True}


def verify_lock():
    lock = read(LOCK)
    for section in ('new_design_code_sha256', 'protected_sha256'):
        for p, h in lock[section].items():
            check(sha(p) == h, 'locked file changed: ' + p)
    check(read(PLAN) == build_plan(), 'static plan changed')
    return lock


def config_path(i):
    return OUT + '/config_' + str(i).zfill(2) + '.json'


def world_for(config):
    return next(w for w in read(PLAN)['worlds'] if w['world_id'] == config['world_id'])


def legacy_projection(run):
    x = deepcopy(run)
    x['evaluation_episode_id'] = 'PRIVATE'
    x['trace']['episode_id'] = 'PRIVATE'
    x['trace']['trace_id'] = 'PRIVATE'
    x['result']['episode_id'] = 'PRIVATE'
    x['result']['trace_id'] = 'PRIVATE'
    return x


def run_slot(config, e, arm):
    return old.simulate(e, arm, config['review_delay_ms'])


def baseline_gate():
    verify_lock()
    slots = []
    for i, c in enumerate(read(PLAN)['configurations']):
        world = world_for(c)
        if world['arrival_regime'] != 'original' or c['review_delay_ms'] != 0:
            continue
        e = input_for(world)
        run = run_slot(c, e, 'retain')
        ref = read(world['old_early_reference_path'])['runs'][0]
        check(legacy_projection(run) == legacy_projection(ref), 'fresh original baseline mismatch')
        old.audit(e, run)
        slots.append({'index': i, 'config': c, 'input': e, 'run': run,
                      'exact_old_same_engine_reproduction': True})
    check(len(slots) == 4, 'four baseline runs required')
    return {'status': 'all_four_fresh_baselines_passed', 'runs_counted_in_formal_88': True,
            'lock_sha256': sha(LOCK), 'slots': slots}


def execute_config(i):
    verify_lock()
    gate = read(GATE)
    check(gate['status'] == 'all_four_fresh_baselines_passed' and gate['lock_sha256'] == sha(LOCK), 'gate missing')
    c = read(PLAN)['configurations'][i]
    world = world_for(c)
    e = input_for(world)
    saved = next((s for s in gate['slots'] if s['index'] == i), None)
    retain = saved['run'] if saved is not None else run_slot(c, e, 'retain')
    runs = [retain, run_slot(c, e, 'replan')]
    pair = old.pair_audit(e, runs)
    pred = c['prediction']
    passed = all(all(pair['audits'][j]['tasks']['water'][k] == pred['water'][arm][k]
                     for k in ('start_ms', 'completion_ms')) for j, arm in enumerate(old.ARMS))
    passed = passed and sorted(pair['running_task_ids']) == pred['expected_running_task_ids']
    passed = passed and sorted(pair['unstarted_task_ids']) == pred['expected_unstarted_task_ids']
    check(pair['commit_ms'] == pred['commit_ms'], 'review clock differs')
    # Prediction failure is a scientific outcome; do not assert or suppress it.
    return {'config': c, 'world': world, 'input': e, 'lock_sha256': sha(LOCK),
            'runs': runs, 'pair': pair, 'prediction_matches': passed,
            'fresh_baseline_gate_reuse': saved is not None}


def future_diagnostics(world_number):
    verify_lock()
    records = []
    for i, c in enumerate(read(PLAN)['configurations']):
        world = world_for(c)
        if (world['world_id'] != 'LW1-W' + str(world_number).zfill(2)
                or world['arrival_regime'] != 'near_start' or c['review_delay_ms'] != 0):
            continue
        main = read(config_path(i))
        cutoff = next(t['release_at_ms'] for t in main['input']['task_stream'] if t['task_id'] == 'water')
        for arm, original in zip(old.ARMS, main['runs']):
            for case in ('different_arrival', 'different_request', 'no_future_request'):
                e = old.counterfactual(main['input'], case)
                run = old.simulate(e, arm, 0)
                def prefix(r):
                    return {'calls': [x for x in r['calls'] if x['request']['current_time_ms'] < cutoff],
                            'events': [x for x in r['trace']['events'] if x['timestamp_ms'] < cutoff]}
                check(prefix(original) == prefix(run), 'future leakage')
                records.append({'world_id': world['world_id'], 'case': case, 'arm': arm,
                                'cutoff_ms': cutoff, 'prefix_equal': True, 'input': e, 'run': run})
    check(len(records) == 6, 'per-world diagnostic scope')
    return {'records': records, 'diagnostic_runs': 6, 'not_in_service_denominator': True,
            'lock_sha256': sha(LOCK)}


def task_delta(a, b):
    out = {}
    for tid in a['required_task_ids']:
        out[tid] = {k: b['tasks'][tid][k] - a['tasks'][tid][k]
                    if a['tasks'][tid][k] is not None and b['tasks'][tid][k] is not None else None
                    for k in ('start_ms', 'completion_ms', 'completion_latency_ms', 'tardiness_ms')}
        out[tid]['completed_by_arm'] = [a['tasks'][tid]['completed'], b['tasks'][tid]['completed']]
        out[tid]['timely_by_arm'] = [a['tasks'][tid]['timely'], b['tasks'][tid]['timely']]
    return out


def all_slot_common(rows):
    """No two/four-cell effects are applied to a many-slot intersection."""
    E = rows[0]['required_task_ids']
    check(all(r['required_task_ids'] == E for r in rows), 'many-slot E mismatch')
    K = [t for t in E if all(t in r['completed_task_ids'] for r in rows)]
    return {'required_task_ids': E, 'common_task_ids': K, 'required_count': len(E),
            'common_count': len(K), 'coverage': len(K)/len(E),
            'eligible': bool(K), 'null_reason': None if K else 'no_common_completed_requests',
            'excluded_tasks': [{'task_id': t, 'not_completed_slot_indices': [i for i, r in enumerate(rows)
                                                                         if t not in r['completed_task_ids']]}
                               for t in E if t not in K],
            'metrics': {m: {'slot_means': [sum(r['tasks'][t][m] for t in K)/len(K) if K else None
                                          for r in rows]} for m in old.TIME_NAMES}}


def scalar_delta(a, b):
    def delta(k):
        x, y = a['metrics'][k], b['metrics'][k]
        return y-x if x is not None and y is not None else None
    return {k: delta(k) for k in ('service_rate', 'timely_service_rate', 'whole_house_completion_ms',
                                  'executed_capacity_violation_duration_ms', 'excess_resource_unit_ms')}


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
    check(len(delay_contrasts) == 40 and len(adjacent) == 36 and len(diagnostics['records']) == 24, 'statistics scope')
    return {'status': 'author_recount_not_independent_review', 'scope': plan['scope'],
            'prediction_matches': sum(d['prediction_matches'] for d in docs), 'predictions_total': 44,
            'worlds': worlds, 'delay_contrasts': delay_contrasts, 'adjacent_delay_contrasts': adjacent,
            'protected_hashes_matched': len(lock['protected_sha256']),
            'raw_artifact_sha256': {config_path(i): sha(config_path(i)) for i in range(44)},
            'plan_sha256': sha(PLAN), 'lock_sha256': sha(LOCK),
            'api_calls': 0, 'holdout_read': False, 'independent_acceptance': None,
            'novelty_proved': False, 'deployment_latency_measured': False, 'rankings': False}


def main():
    cmd = sys.argv[1]
    if cmd == 'plan':
        result = build_plan()
    elif cmd == 'lock':
        result = make_lock()
    elif cmd == 'gate':
        result = baseline_gate()
    elif cmd == 'run':
        result = execute_config(int(sys.argv[2]))
    elif cmd == 'diagnostics':
        result = future_diagnostics(int(sys.argv[2]))
    elif cmd == 'statistics':
        result = build_statistics()
    else:
        raise ValueError('unknown command')
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
