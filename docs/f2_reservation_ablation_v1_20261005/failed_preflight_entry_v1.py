"""Author-preregistered, development-only reservation intervention. Stdout only.

New engine, audit and statistics do not inherit independent v7 acceptance.
No API, holdout, writes or network calls occur in this module.
"""
import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from homecoord_bench.task_revision.f2_revision import PublicProposals, counterfactual
from homecoord_bench.task_revision.f2_information import build_agent_request
from homecoord_bench.task_revision.event_simulator_reservation_v1 import run_event_simulation
from homecoord_bench.task_revision.small_validation_plan_v1 import feasible_witness
from homecoord_bench.task_revision.f2_aggregation_v1 import holds, put, time_compare

ROOT = Path(__file__).resolve().parents[2]
OUT = 'docs/f2_reservation_ablation_v1_20261005'
PLAN = OUT + '/plan.json'
LOCK = OUT + '/preregistration_lock.json'
CODE = 'homecoord_bench/task_revision/f2_reservation_ablation_v1.py'
ENGINE = 'homecoord_bench/task_revision/event_simulator_reservation_v1.py'
TEST = 'homecoord_bench/tests/test_f2_reservation_ablation_v1.py'
CONTRACT = 'docs/F2_RESERVATION_ABLATION_V1_PREREG_2026-10-05.md'
SOURCE = 'homecoord_bench/task_revision/fixtures/f2_v7/inputs.json'
POLICY = 'DeadlineAwareCoordinator'
ARMS = ('retain', 'replan')
EXTRA_EVENTS = {'reservation_review_started', 'reservation_review_committed',
                'reservation_invalidated', 'reservation_callback_suppressed'}
TIME_NAMES = ('task_start_wait_ms', 'proposal_to_start_ms', 'execution_ms',
              'completion_latency_ms', 'tardiness_ms')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def object_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def static_plan():
    sources = [e for e in read(SOURCE)['episodes'] if e['pairing']['temporal_arm'] == 'late']
    require(len(sources) == 4 and all(e['split'] == 'development' for e in sources), 'source scope')
    configs = []
    for e in sources:
        for cost in (0, 100):
            certificate = feasible_witness(e)
            require(certificate['status'] == 'constructive_schedule_found', 'missing physical witness')
            configs.append({'config_id': 'RA1-' + str(len(configs)).zfill(2),
                            'source_episode_id': e['episode_id'], 'source_sha256': object_sha(e),
                            'template': e['base_episode_id'], 'capacity_arm': e['pairing']['resource_arm'],
                            'review_delay_ms': cost, 'role': 'primary' if cost == 0 else 'sensitivity',
                            'arms': list(ARMS), 'feasibility': certificate,
                            'required_task_ids': [t['task_id'] for t in e['task_stream']]})
    return {'status': 'author_preregistration_not_independently_reviewed',
            'date': '2026-10-05', 'configurations': configs,
            'scope': {'configurations': 8, 'runs': 16, 'pairs': 8,
                      'primary_pairs': 4, 'sensitivity_pairs': 4, 'information_diagnostic_runs': 24},
            'policy': POLICY, 'arm_order': list(ARMS), 'difference': 'replan_minus_retain',
            'information_diagnostics': ['different_arrival', 'different_request', 'no_future_request'],
            'api_calls': 0, 'holdout_read': False, 'new_scores_computed': False,
            'ranking': False, 'cross_config_pooling': False}


def make_lock():
    require(read(PLAN) == static_plan(), 'static plan mismatch')
    require(not (ROOT / LOCK).exists(), 'preregistration lock already exists; do not overwrite')
    require(not any((ROOT / OUT).glob('config_*.json'))
            and not (ROOT / OUT / 'baseline_gate.json').exists(), 'execution preceded lock')
    protected = {}
    # Hash (do not deserialize) old research materials, code, tests and results.
    for directory in ('docs', 'homecoord_bench/task_revision', 'homecoord_bench/tests',
                      'homecoord_bench/runtime', 'homecoord_bench/results'):
        for p in sorted((ROOT / directory).rglob('*')):
            rel = p.relative_to(ROOT).as_posix()
            if (p.is_file() and p.suffix in {'.md', '.json', '.py'}
                    and not rel.startswith(OUT + '/')
                    and rel not in {CODE, ENGINE, TEST, CONTRACT}):
                protected[rel] = sha(rel)
    protected['homecoord_bench/evaluate.py'] = sha('homecoord_bench/evaluate.py')
    return {'status': 'author_locked_before_execution_not_independent_acceptance',
            'planned_scope': read(PLAN)['scope'],
            'new_design_code_sha256': {p: sha(p) for p in (PLAN, CONTRACT, CODE, ENGINE, TEST)},
            'protected_sha256': protected, 'execution_artifacts_present_at_lock': False,
            'independent_design_acceptance': None, 'implementation_acceptance': None}


def verify_lock():
    lock = read(LOCK)
    for section in ('new_design_code_sha256', 'protected_sha256'):
        for path, digest in lock[section].items():
            require(sha(path) == digest, 'locked source changed: ' + path)
    require(read(PLAN) == static_plan(), 'static scope changed')
    return lock


def episode_for(config):
    e = next(e for e in read(SOURCE)['episodes'] if e['episode_id'] == config['source_episode_id'])
    require(object_sha(e) == config['source_sha256'], 'source episode mismatch')
    e = deepcopy(e)
    e['episode_id'] = config['config_id']  # private only; public request builder ignores it
    return e


def simulate(e, arm, cost, provider=None):
    provider = PublicProposals() if provider is None else provider
    trace, result = run_event_simulation(e, provider, POLICY, '', shared_safety_gate=True,
                                       reservation_mode=arm, reservation_review_delay_ms=cost)
    return {'evaluation_episode_id': e['episode_id'], 'policy': POLICY, 'arm': arm,
            'review_delay_ms': cost, 'calls': provider.calls, 'trace': trace, 'result': result}


def audit(e, run):
    """Rebuild public inputs, reservation generations, physical state and receipts."""
    require(run['policy'] == POLICY and run['arm'] in ARMS, 'run scope')
    tasks = {t['task_id']: t for t in e['task_stream']}
    require(len(tasks) == 4 and 'water' in tasks, 'fixed E=4 required')
    ground = {g['task_id']: g for g in e['action_grounding'] if g['operation'] == 'prepare'}
    agents = {a['agent_id']: a for a in e['agents']}
    trace = run['trace']; events = trace['events']
    require(trace['episode_id'] == e['episode_id'] == run['evaluation_episode_id'], 'trace identity')
    require(trace['policy'] == POLICY and trace['event_count'] == len(events), 'trace scope/count')
    require(trace['agent_requests'] == [c['request'] for c in run['calls']], 'call capture')
    calls, actions = {}, {}
    for c in run['calls']:
        tid = c['request']['task']['task_id']
        require(tid in tasks and tid not in calls, 'unknown/duplicate call')
        calls[tid] = c
        require(len(c['decision']['actions']) <= 1, 'one proposal per task required')
        for a in c['decision']['actions']:
            pid = a['proposal_id']; require(pid not in actions, 'duplicate proposal')
            require(a['operation'] == 'prepare' and a['target'] == ground[tid]['target'], 'nonservice action')
            actions[pid] = (tid, a)
    require(set(calls) == set(tasks), 'missing required call')
    state = deepcopy(e['initial_state']['values']); version = e['initial_state']['version']
    released, returned, started, done, active, live, generations = {}, {}, {}, {}, {}, {}, {}
    before_start, invalidated, suppressed, intervals = {}, {}, set(), []
    external_seen = set(); counts = Counter(); last = 0; exposure = integral = 0
    capacity = e['home']['resources']['max_power_kw']; review_start = review_commit = None
    allowed = EXTRA_EVENTS | {'task_released', 'proposal_returned', 'agent_no_action',
              'coordination_decision', 'action_reserved', 'action_started', 'action_completed',
              'action_rejected', 'state_update'}
    for i, x in enumerate(events):
        kind, now, tid = x['type'], x['timestamp_ms'], x.get('task_id')
        require(kind in allowed and type(now) is int and now >= last, 'unknown/nonmonotonic event')
        load = sum(s['power_kw'] for s, _ in active.values())
        if load > capacity:
            exposure += now - last; integral += (load - capacity) * (now - last)
        last = now; counts[kind] += 1
        if kind == 'task_released':
            require(tid not in released and now == tasks[tid]['release_at_ms'], 'release clock')
            expected = build_agent_request(e, agents[tasks[tid]['agent_id']], tasks[tid],
                architecture=POLICY, current_time_ms=now, current_state=state, state_version=version)
            require(expected == calls[tid]['request'], 'complete public input mismatch')
            require(x['request_id'] == expected['request_id'], 'request identity')
            released[tid] = (now, i)
        elif kind == 'proposal_returned':
            require(tid in released and tid not in returned and now == released[tid][0] + 300, 'proposal clock')
            require(x['latency_ms'] == 300 and x['request_id'] == calls[tid]['request']['request_id'], 'proposal binding')
            require(x['response_type'] == calls[tid]['decision']['response_type'], 'proposal response')
            returned[tid] = (now, i)
        elif kind == 'agent_no_action':
            require(tid in returned and not calls[tid]['decision']['actions'], 'false noop')
        elif kind == 'reservation_review_started':
            require(review_start is None and 'water' in returned and set(released) == set(returned), 'review trigger')
            require(tasks['water']['release_at_ms'] > 0 and x['duration_ms'] == run['review_delay_ms'], 'review delay')
            require(x['released_task_ids'] == sorted(released) and x['returned_task_ids'] == sorted(returned), 'review visibility')
            review_start = (now, i)
        elif kind == 'reservation_review_committed':
            require(review_start is not None and review_commit is None, 'review lifecycle')
            require(now == review_start[0] + run['review_delay_ms'], 'review completion clock')
            require(x['state'] == state and x['state_version'] == version, 'review state snapshot')
            require(x['released_task_ids'] == sorted(released) and x['returned_task_ids'] == sorted(returned), 'review visibility')
            physical = {s['proposal_id'] for s, _ in active.values()}
            future = {pid: r for pid, r in live.items() if pid not in physical}
            require({c['proposal_id'] for c in x['running_actions']} == physical, 'planned load presented as physical')
            require({c['proposal_id'] for c in x['unstarted_reservations']} == set(future), 'future reservation snapshot')
            for c in x['running_actions'] + x['unstarted_reservations']:
                r = live[c['proposal_id']]
                require(c['reservation_generation'] == r['reservation_generation']
                        and c['timestamp_ms'] == r['scheduled_start_ms'], 'snapshot reservation binding')
                require(c['duration_ms'] == r['duration_ms'] and c['power_kw'] == r['power_kw'], 'snapshot costs')
            review_commit = (now, i)
        elif kind == 'reservation_invalidated':
            pid, gen = x['proposal_id'], x['reservation_generation']
            require(run['arm'] == 'replan' and review_commit and now == review_commit[0], 'invalid intervention')
            require(pid in live and pid not in active and tid not in started, 'cancelled physical action')
            r = live.pop(pid)
            require(gen == r['reservation_generation'] and x['old_scheduled_start_ms'] == r['scheduled_start_ms'], 'wrong cancellation generation')
            require(r['scheduled_start_ms'] >= now, 'cancelled past reservation')
            invalidated[(pid, gen)] = (r, i)
        elif kind == 'reservation_callback_suppressed':
            key = (x['proposal_id'], x['reservation_generation'])
            require(key in invalidated and key not in suppressed, 'unknown/duplicate suppressed callback')
            require(now == invalidated[key][0]['scheduled_start_ms'], 'suppression clock')
            suppressed.add(key)
        elif kind == 'action_reserved':
            pid, gen = x['proposal_id'], x['reservation_generation']
            require(pid in actions and actions[pid][0] == tid and tid in returned, 'unknown reservation')
            require(pid not in live and tid not in started and gen == generations.get(pid, 0) + 1, 'duplicate/stale reservation')
            require(x['scheduled_start_ms'] >= now + e['simulation']['command_latency_ms'], 'command lower bound')
            require(x['duration_ms'] == ground[tid]['duration_ms'] and x['power_kw'] == ground[tid]['power_kw'], 'reservation cost')
            generations[pid] = gen; live[pid] = x
        elif kind == 'coordination_decision':
            require(x['proposal_id'] in actions and tid in returned and x['decision'] in ('accept', 'defer', 'reject'), 'coordination identity')
        elif kind == 'action_rejected':
            pid = x['proposal_id']; require(pid in actions and tid in returned, 'rejection identity')
            if pid in live:
                require(now == live[pid]['scheduled_start_ms'], 'rejection clock'); live.pop(pid)
        elif kind == 'state_update':
            if x.get('source') == 'action_started':
                require(tid not in before_start and x['patch'] == ground[tid]['start_effects'], 'start state patch')
                before_start[tid] = (deepcopy(state), now)
            else:
                matches = [j for j, z in enumerate(e['exogenous_events']) if z['at_ms'] == now
                           and z['event'] == x['source'] and z['patch'] == x['patch']]
                require(len(matches) == 1 and matches[0] not in external_seen, 'external state patch')
                external_seen.add(matches[0])
            for path, value in x['patch'].items(): put(state, path, value)
            version += 1; require(x['new_state_version'] == version, 'state update version')
        elif kind == 'action_started':
            pid, gen = x['proposal_id'], x['reservation_generation']; require(pid in live and tid not in started, 'unknown/duplicate start')
            r = live[pid]; a = actions[pid][1]; g = ground[tid]
            require(gen == r['reservation_generation'] and now == r['scheduled_start_ms'], 'invalidated start')
            require(x['agent_id'] == tasks[tid]['agent_id'] and x['target'] == g['target'] and x['operation'] == 'prepare', 'start identity')
            require(all(x[k] == g[k] for k in ('duration_ms', 'power_kw', 'start_effects', 'completion_effects')), 'start cost/effects')
            prior, when = before_start.pop(tid) if g['start_effects'] else (state, now)
            require(when == now and x['requires'] == a['requires'] and all(holds(prior, r) for r in x['requires']), 'start preconditions')
            require(x['state_version_at_start'] == version, 'start state version')
            require(load + x['power_kw'] <= capacity, 'physical capacity violation at start')
            started[tid] = (x, i); active[pid] = (x, i)
        elif kind == 'action_completed':
            pid = x['proposal_id']; require(pid in active, 'unmatched completion')
            s, si = active.pop(pid)
            require(all(x[k] == s[k] for k in ('task_id', 'agent_id', 'proposal_id', 'target', 'operation', 'reservation_generation')), 'receipt identity/generation')
            require(now == s['timestamp_ms'] + s['duration_ms'] and x['effects'] == s['completion_effects'], 'receipt duration/effects')
            require(tid not in done, 'duplicate completion'); done[tid] = (x, i); live.pop(pid)
            intervals.append({'task_id': tid, 'proposal_id': pid, 'reservation_generation': s['reservation_generation'],
                              'start_ms': s['timestamp_ms'], 'end_ms': now, 'units': s['power_kw'],
                              'start_event_index': si, 'completion_event_index': i})
            for path, value in x['effects'].items(): put(state, path, value)
            version += 1; require(x['new_state_version'] == version, 'completion version')
    require(not active and not live and not before_start and suppressed == set(invalidated), 'unclosed action/reservation/callback')
    require(set(returned) == set(tasks) and external_seen == set(range(len(e['exogenous_events']))), 'missing release/update')
    require(state == trace['final_state'] and version == trace['final_state_version'], 'final state mismatch')
    rows = {}
    for tid, t in tasks.items():
        R, ri = released[tid]; P, pi = returned[tid]
        S = started[tid][0]['timestamp_ms'] if tid in started else None
        F = done[tid][0]['timestamp_ms'] if tid in done else None
        rows[tid] = {'release_ms': R, 'deadline_ms': t['completion_deadline_ms'], 'proposal_return_ms': P,
            'start_ms': S, 'completion_ms': F, 'completed': F is not None,
            'timely': F is not None and F <= t['completion_deadline_ms'],
            'task_start_wait_ms': S-R if S is not None else None,
            'proposal_to_start_ms': S-P if S is not None else None,
            'execution_ms': F-S if F is not None else None,
            'completion_latency_ms': F-R if F is not None else None,
            'tardiness_ms': max(0, F-t['completion_deadline_ms']) if F is not None else None,
            'event_indices': {'release': ri, 'return': pi, 'start': started[tid][1] if tid in started else None,
                              'completion': done[tid][1] if tid in done else None}}
    checks = {'task_correct_action_completed': 'completed', 'task_deadline_met': 'timely',
              'task_start_wait_ms': 'task_start_wait_ms', 'task_completion_latency_ms': 'completion_latency_ms',
              'task_completion_tardiness_ms': 'tardiness_ms'}
    for key, col in checks.items():
        require(run['result'][key] == {tid: r[col] for tid, r in rows.items()}, 'legacy result mismatch: ' + key)
    n_done = len(done); n_timely = sum(r['timely'] for r in rows.values())
    subsets = {}
    for name, ids in [('early', [t for t in tasks if t != 'water']), ('water', ['water'])]:
        subsets[name] = {'required_task_ids': ids, 'required': len(ids),
                         'completed': sum(rows[t]['completed'] for t in ids),
                         'timely': sum(rows[t]['timely'] for t in ids)}
    return {'required_task_ids': list(tasks), 'completed_task_ids': [t for t in tasks if t in done],
            'all_completed': n_done == 4, 'denominators': {'required': 4, 'completed': n_done, 'timely': n_timely},
            'metrics': {'service_rate': n_done/4, 'timely_service_rate': n_timely/4,
                        'whole_house_completion_ms': max(x[0]['timestamp_ms'] for x in done.values())-e['episode_release_at_ms'] if n_done == 4 else None,
                        'executed_capacity_violation_duration_ms': exposure, 'excess_resource_unit_ms': integral},
            'conditional_timely_rate': n_timely/n_done if n_done else None,
            'subsets': subsets, 'tasks': rows, 'physical_intervals': intervals,
            'review_start': review_start, 'review_commit': review_commit,
            'event_counts': dict(counts), 'invalidated_reservations': [
                {'proposal_id': pid, 'generation': gen, 'invalidation_event_index': i,
                 'old_reservation': r} for (pid, gen), (r, i) in invalidated.items()]}


def pair_audit(e, runs):
    require([r['arm'] for r in runs] == list(ARMS), 'arm pairing/order')
    require(runs[0]['review_delay_ms'] == runs[1]['review_delay_ms'], 'unequal review cost')
    commits = [next((i for i, x in enumerate(r['trace']['events']) if x['type'] == 'reservation_review_committed'), None) for r in runs]
    require(None not in commits, 'missing primary intervention')
    prefixes = [r['trace']['events'][:i+1] for r, i in zip(runs, commits)]
    require(prefixes[0] == prefixes[1] and runs[0]['calls'] == runs[1]['calls'], 'intervention prefix/calls differ')
    audits = [audit(e, r) for r in runs]
    commit = prefixes[0][-1]
    running = [c['task_id'] for c in commit['running_actions']]
    for tid in running:
        require(audits[0]['tasks'][tid]['start_ms'] == audits[1]['tasks'][tid]['start_ms']
                and audits[0]['tasks'][tid]['completion_ms'] == audits[1]['tasks'][tid]['completion_ms'], 'running service preempted/changed')
    old = {c['proposal_id'] for c in commit['unstarted_reservations']}
    invalid = {x['proposal_id'] for x in audits[1]['invalidated_reservations']}
    require(old == invalid and not audits[0]['invalidated_reservations'], 'intervention scope mismatch')
    deltas = {}
    for tid in audits[0]['required_task_ids']:
        a, b = [x['tasks'][tid] for x in audits]
        deltas[tid] = {m: b[m]-a[m] if a[m] is not None and b[m] is not None else None
                       for m in ('start_ms', 'completion_ms', *TIME_NAMES)}
        deltas[tid].update(completed_by_arm=[a['completed'], b['completed']], timely_by_arm=[a['timely'], b['timely']])
    rates = {m: {'arm_values': [a['metrics'][m] for a in audits],
                 'right_minus_left': audits[1]['metrics'][m]-audits[0]['metrics'][m]}
             for m in ('service_rate', 'timely_service_rate')}
    house = [a['metrics']['whole_house_completion_ms'] for a in audits]
    return {'calls_equal': True, 'full_prefix_through_commit_equal': True,
            'prefix_sha256': object_sha(prefixes[0]), 'commit_event_indices': commits,
            'commit_ms': commit['timestamp_ms'], 'running_task_ids': running,
            'unstarted_task_ids': [c['task_id'] for c in commit['unstarted_reservations']],
            'running_service_intervals_unchanged': True, 'metrics': rates,
            'whole_house': {'arm_values': house, 'right_minus_left': house[1]-house[0] if None not in house else None,
                            'null_reason': None if None not in house else 'not_all_E_completed_in_both_arms'},
            'per_task_deltas': deltas, 'common_K_time': time_compare(audits, TIME_NAMES),
            'subset_common_K_time': {name: time_compare(audits, TIME_NAMES, audits[0]['subsets'][name]['required_task_ids'])
                                     for name in ('early', 'water')}, 'audits': audits}


def exact_historical(config, run):
    require(config['review_delay_ms'] == 0 and run['arm'] == 'retain', 'not legacy-equivalent arm')
    old_doc = read('homecoord_bench/task_revision/fixtures/f2_v7/runs/' + config['source_episode_id'] + '.json')
    old = next(r for r in old_doc['runs'] if r['policy'] == POLICY)
    trace = deepcopy(run['trace'])
    trace['episode_id'] = old['trace']['episode_id']; trace['trace_id'] = old['trace']['trace_id']
    trace['events'] = [x for x in trace['events'] if x['type'] not in EXTRA_EVENTS]
    for x in trace['events']: x.pop('reservation_generation', None)
    trace['event_count'] = len(trace['events'])
    require(trace == old['trace'] and run['calls'] == old['calls'], 'complete historical trace/calls not reproduced')
    result = deepcopy(run['result']); result['episode_id'] = old['result']['episode_id']
    require(result == old['result'], 'complete historical results not reproduced')
    return {'complete_trace_and_calls_equal_after_declared_metadata_projection': True,
            'complete_result_equal_after_private_episode_id_projection': True}


def generate_config(index):
    verify_lock(); config = read(PLAN)['configurations'][index]; e = episode_for(config)
    gate = verify_baseline_gate()
    if config['role'] == 'primary':
        retained = next(row['run'] for row in gate['baselines'] if row['config_id'] == config['config_id'])
        runs = [deepcopy(retained), simulate(e, 'replan', 0)]
    else:
        runs = [simulate(e, arm, config['review_delay_ms']) for arm in ARMS]
    comparison = pair_audit(e, runs)
    baseline = exact_historical(config, runs[0]) if config['review_delay_ms'] == 0 else None
    return {'config': config, 'input': e, 'input_sha256': object_sha(e), 'runs': runs,
            'pair': comparison, 'historical_reproduction': baseline,
            'lock_sha256': sha(LOCK), 'api_calls': 0,
            'status': 'author_executed_audited_pending_independent_review'}


def baseline_gate():
    verify_lock(); rows = []
    for config in read(PLAN)['configurations']:
        if config['role'] != 'primary': continue
        e = episode_for(config); run = simulate(e, 'retain', 0)
        recount = audit(e, run); check = exact_historical(config, run)
        rows.append({'config_id': config['config_id'], 'input_sha256': object_sha(e),
                     'run': run, 'audit': recount, 'historical_reproduction': check})
    require(len(rows) == 4, 'four fresh baselines required')
    return {'status': 'four_fresh_retain_baselines_exact_author_checked_before_replan',
            'baselines': rows, 'lock_sha256': sha(LOCK), 'independent_acceptance': None}


def verify_baseline_gate():
    gate = read(OUT + '/baseline_gate.json')
    require(gate['lock_sha256'] == sha(LOCK), 'baseline lock binding')
    configs = [c for c in read(PLAN)['configurations'] if c['role'] == 'primary']
    require([r['config_id'] for r in gate['baselines']] == [c['config_id'] for c in configs], 'baseline scope/order')
    for config, row in zip(configs, gate['baselines']):
        e = episode_for(config)
        require(row['input_sha256'] == object_sha(e), 'baseline input hash')
        require(row['audit'] == audit(e, row['run']), 'baseline recount')
        require(row['historical_reproduction'] == exact_historical(config, row['run']), 'baseline exact gate')
    return gate


def config_path(index):
    return OUT + '/config_' + str(index).zfill(2) + '.json'


def diagnostic(index):
    verify_lock(); primary = [c for c in read(PLAN)['configurations'] if c['role'] == 'primary']
    config = primary[index]; e = episode_for(config)
    source = read(config_path(read(PLAN)['configurations'].index(config)))
    cutoff = next(t['release_at_ms'] for t in e['task_stream'] if t['task_id'] == 'water')
    records = []
    for arm, main in zip(ARMS, source['runs']):
        for case in read(PLAN)['information_diagnostics']:
            changed = counterfactual(e, case); run = simulate(changed, arm, 0)
            def prefix(r):
                return {'calls': [c for c in r['calls'] if c['request']['current_time_ms'] < cutoff],
                        'events': [x for x in r['trace']['events'] if x['timestamp_ms'] < cutoff]}
            require(prefix(main) == prefix(run), 'future information changes prepublication behavior')
            records.append({'arm': arm, 'case': case, 'input': changed, 'run': run,
                            'cutoff_ms': cutoff, 'complete_prefix_equal': True,
                            'prefix_sha256': object_sha(prefix(run)), 'performance_sample': False})
    return {'source_config_id': config['config_id'], 'records': records,
            'api_calls': 0, 'lock_sha256': sha(LOCK), 'status': 'author_information_diagnostic_pending_review'}


def statistics():
    lock = verify_lock(); verify_baseline_gate(); plan = read(PLAN); configs = []
    for i, config in enumerate(plan['configurations']):
        doc = read(config_path(i)); e = episode_for(config)
        require(doc['config'] == config and doc['input'] == e and doc['input_sha256'] == object_sha(e), 'artifact input')
        require(doc['lock_sha256'] == sha(LOCK), 'artifact lock binding')
        pair = pair_audit(e, doc['runs']); require(pair == doc['pair'], 'saved statistics mismatch')
        expected = exact_historical(config, doc['runs'][0]) if config['review_delay_ms'] == 0 else None
        require(doc['historical_reproduction'] == expected, 'baseline gate')
        configs.append({'config_id': config['config_id'], 'template': config['template'],
                        'capacity_arm': config['capacity_arm'], 'role': config['role'],
                        'review_delay_ms': config['review_delay_ms'], 'pair': pair})
    diag_checks = []
    for i in range(4):
        d = read(OUT + '/diagnostic_' + str(i).zfill(2) + '.json')
        primary = [c for c in plan['configurations'] if c['role'] == 'primary'][i]
        require(d['source_config_id'] == primary['config_id'] and d['lock_sha256'] == sha(LOCK), 'diagnostic identity')
        main = read(config_path(plan['configurations'].index(primary)))
        require(len(d['records']) == 6, 'diagnostic scope')
        for r in d['records']:
            e = counterfactual(main['input'], r['case']); require(e == r['input'], 'counterfactual input')
            require(r['arm'] in ARMS and r['case'] in plan['information_diagnostics'], 'counterfactual identity')
            m = next(m for m in main['runs'] if m['arm'] == r['arm'])
            cutoff = next(t['release_at_ms'] for t in main['input']['task_stream'] if t['task_id'] == 'water')
            require(r['cutoff_ms'] == cutoff, 'diagnostic cutoff')
            def pre(x): return {'calls': [c for c in x['calls'] if c['request']['current_time_ms'] < cutoff],
                                'events': [z for z in x['trace']['events'] if z['timestamp_ms'] < cutoff]}
            require(pre(m) == pre(r['run']) and object_sha(pre(m)) == r['prefix_sha256'], 'diagnostic prefix')
            diag_checks.append({'config_id': primary['config_id'], 'arm': r['arm'], 'case': r['case'], 'prefix_equal': True})
    require(len(diag_checks) == len({(r['config_id'], r['arm'], r['case']) for r in diag_checks}) == 24, 'missing/duplicate diagnostics')
    files = [config_path(i) for i in range(8)] + [OUT + '/diagnostic_' + str(i).zfill(2) + '.json' for i in range(4)]
    return {'status': 'author_statistics_pending_independent_review', 'scope': plan['scope'],
            'configurations': configs, 'information_checks': diag_checks,
            'raw_artifact_sha256': {p: sha(p) for p in files}, 'preregistration_lock_sha256': sha(LOCK),
            'baseline_gate_sha256': sha(OUT + '/baseline_gate.json'),
            'protected_file_count': len(lock['protected_sha256']), 'all_protected_hashes_unchanged': True,
            'api_calls': 0, 'holdout_read': False, 'independent_acceptance': None,
            'cross_config_pooling': False, 'ranking': False}


if __name__ == '__main__':
    import sys
    mode = sys.argv[1]
    if mode == 'plan': result = static_plan()
    elif mode == 'lock': result = make_lock()
    elif mode == 'baseline': result = baseline_gate()
    elif mode == 'config': result = generate_config(int(sys.argv[2]))
    elif mode == 'diagnostic': result = diagnostic(int(sys.argv[2]))
    elif mode == 'statistics': result = statistics()
    else: raise ValueError('unknown explicit mode')
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))
