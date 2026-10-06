"""Frozen F1 event aggregation only. No simulator, API or reported-result reuse."""
import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from homecoord_bench.task_revision.f1_statistical_contract_v2 import (
    ROOT, CELL_ORDER, MAIN_RATES, TIME_METRICS, RUN_METRICS, analysis_population,
)

FREEZE = 'docs/f1_statistical_contract_v2_20261004/freeze_20261004.json'
FREEZE_SHA = '027e0feaea38167306acd58cb7329cb27bc8dac2e9081478034d07f5050ca795'
OUT = 'docs/f1_aggregation_v1_20261004'


class EvidenceError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise EvidenceError(message)


def read(path, root=ROOT):
    try:
        return json.loads((Path(root) / path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise EvidenceError(str(exc)) from exc


def digest(path, root=ROOT):
    try:
        return hashlib.sha256((Path(root) / path).read_bytes()).hexdigest()
    except OSError as exc:
        raise EvidenceError(str(exc)) from exc


def get(state, path):
    for key in path.split('.'):
        if not isinstance(state, dict) or key not in state:
            return None
        state = state[key]
    return state


def put(state, path, val):
    keys = path.split('.')
    for key in keys[:-1]:
        state = state.setdefault(key, {})
    state[keys[-1]] = val


def holds(state, rule):
    a, b, op = get(state, rule['path']), rule['value'], rule['op']
    if op == 'eq': return a == b
    if op == 'neq': return a != b
    if a is None: return False
    if op == 'lt': return a < b
    if op == 'lte': return a <= b
    if op == 'gt': return a > b
    if op == 'gte': return a >= b
    if op == 'between': return b[0] <= a <= b[1]
    raise EvidenceError('unknown precondition operator')


def recount(episode, run):
    """Validate identities, reconstruct state and physical intervals, then score E."""
    tasks = {t['task_id']: t for t in episode['task_stream']}
    require(tasks and len(tasks) == len(episode['task_stream']), 'invalid required set')
    require(run['episode_id'] == episode['episode_id'], 'episode identity mismatch')
    trace = run['trace']
    require(trace['episode_id'] == episode['episode_id'] and trace['policy'] == run['policy'], 'trace identity mismatch')
    require(not episode.get('constraints') and not episode.get('exogenous_events'), 'outside F1 scope')
    state = deepcopy(episode['initial_state']['values']); version = episode['initial_state']['version']
    calls, proposals = {}, {}
    agents = {a['agent_id']: a for a in episode['agents']}
    for call in run['calls']:
        r = call['request']; tid = r['task']['task_id']
        require(tid in tasks and tid not in calls, 'duplicate/unknown call task')
        require(r['episode_id'] == episode['episode_id'] and r['architecture'] == run['policy'], 'call scope mismatch')
        require(r['current_time_ms'] == tasks[tid]['release_at_ms'], 'call release mismatch')
        agent = agents[tasks[tid]['agent_id']]
        require(r['agent'] == agent and r['allowed_tools'] == agent['tools'], 'call permission mismatch')
        require(r['available_actions'] == [t for t in episode['tool_catalog'] if t['agent_id'] == agent['agent_id']], 'tool list mismatch')
        require(call['decision']['response_type'] == 'action_proposal', 'invalid response type')
        calls[tid] = call
        for action in call['decision']['actions']:
            pid = action['proposal_id']
            require(pid not in proposals, 'duplicate proposal identity')
            require(any((t['target'], t['operation']) == (action['target'], action['operation']) for t in r['available_actions']), 'unauthorized proposal')
            proposals[pid] = (tid, action)
    require(set(calls) == set(tasks), 'missing call task')
    require(trace['agent_requests'] == [c['request'] for c in run['calls']], 'captured request mismatch')
    released, returned, active, started, done = {}, {}, {}, {}, {}
    counts = Counter(); affected = defaultdict(set); reasons = defaultdict(Counter)
    intervals, safety_intervals, preconditions, before_start = [], [], [], {}
    last = 0; excess_ms = 0; excess_integral = 0
    capacity = episode['home']['resources']['max_power_kw']
    allowed_events = {'task_released', 'proposal_returned', 'coordination_decision', 'action_reserved',
                      'action_started', 'action_completed', 'action_rejected', 'retry_queued', 'retry_scheduled', 'state_update'}
    for i, e in enumerate(trace['events']):
        kind, now, tid = e['type'], e['timestamp_ms'], e.get('task_id')
        require(kind in allowed_events and type(now) is int and now >= last, 'unknown/nonmonotonic event')
        require(tid in tasks, 'unknown event task')
        units = sum(s['power_kw'] for s, _ in active.values())
        if now > last and units > capacity:
            excess_ms += now - last; excess_integral += (now - last) * (units - capacity)
            safety_intervals.append({'start_ms': last, 'end_ms': now, 'load_units': units,
                                     'capacity_units': capacity, 'next_event_index': i})
        last = now
        counts[kind] += 1; affected[kind].add(tid)
        if 'reason' in e:
            reasons[kind][str(e['reason'])] += 1
        if kind == 'task_released':
            require(tid not in released and now == tasks[tid]['release_at_ms'], 'release identity/time mismatch')
            require(e['request_id'] == calls[tid]['request']['request_id'], 'release request mismatch')
            released[tid] = (now, i)
        elif kind == 'proposal_returned':
            require(tid in released and tid not in returned, 'invalid return lifecycle')
            require(e['request_id'] == calls[tid]['request']['request_id'] and e['response_type'] == 'action_proposal', 'return request mismatch')
            require(now - released[tid][0] == calls[tid]['logical_latency_ms'], 'return offset mismatch')
            returned[tid] = (now, i)
        elif kind in ('action_reserved', 'coordination_decision', 'action_rejected'):
            pid = e['proposal_id']
            require(pid in proposals and proposals[pid][0] == tid and tid in returned, 'unknown event proposal')
            if kind == 'coordination_decision':
                require(e['decision'] in ('accept', 'defer', 'reject'), 'unknown coordination decision')
                key = 'coordination_' + e['decision']
                counts[key] += 1; affected[key].add(tid)
        elif kind == 'state_update':
            require(e.get('source') == 'action_started' and tid not in before_start, 'unexpected state update')
            g = [g for g in episode['action_grounding'] if g['task_id'] == tid and g.get('start_effects', {}) == e['patch']]
            require(len(g) == 1, 'start patch mismatch')
            before_start[tid] = (deepcopy(state), now, g[0]['operation'])
            for path, v in e['patch'].items(): put(state, path, v)
            version += 1
            require(e['new_state_version'] == version, 'state version mismatch')
        elif kind == 'action_started':
            pid = e['proposal_id']
            require(tid in returned and pid in proposals and proposals[pid][0] == tid, 'unreleased/unknown start')
            require(now >= returned[tid][0] and pid not in active, 'duplicate/premature start')
            a = proposals[pid][1]
            require((e['target'], e['operation']) == (a['target'], a['operation']), 'start proposal mismatch')
            gs = [g for g in episode['action_grounding'] if g['task_id'] == tid and (g['target'], g['operation']) == (e['target'], e['operation'])]
            require(len(gs) == 1, 'unknown grounding'); g = gs[0]
            require(e['agent_id'] == tasks[tid]['agent_id'], 'start agent mismatch')
            require(all(e[k] == g[k] for k in ('duration_ms', 'power_kw', 'start_effects', 'completion_effects')), 'start cost/effect mismatch')
            s = state
            if g['start_effects']:
                require(tid in before_start, 'missing start state update')
                s, when, op = before_start.pop(tid)
                require((when, op) == (now, e['operation']), 'start patch identity mismatch')
            require(e.get('state_version_at_start') == version, 'start version mismatch')
            canonical = lambda rules: [{k: r[k] for k in ('path', 'op', 'value')} for r in rules]
            require(canonical(e['requires']) == canonical(a['requires']), 'changed start preconditions')
            valid = all(holds(s, r) for r in e['requires'])
            preconditions.append({'task_id': tid, 'event_index': i, 'valid': valid})
            active[pid] = (e, i)
            if any(all(e.get(k) == v for k, v in spec.items()) for spec in tasks[tid]['acceptable_actions']):
                require(tid not in started, 'multiple service attempts outside F1 scope')
                started[tid] = (e, i)
        elif kind == 'action_completed':
            pid = e['proposal_id']
            require(pid in active, 'unmatched completion receipt')
            start, si = active.pop(pid)
            require(all(e[k] == start[k] for k in ('task_id', 'agent_id', 'target', 'operation')), 'receipt identity mismatch')
            require(now == start['timestamp_ms'] + start['duration_ms'] and e['effects'] == start['completion_effects'], 'receipt time/effects mismatch')
            intervals.append({'task_id': tid, 'proposal_id': pid, 'start_event_index': si, 'completion_event_index': i,
                              'start_ms': start['timestamp_ms'], 'end_ms': now, 'units': start['power_kw']})
            for path, val in e['effects'].items(): put(state, path, val)
            version += 1
            require(e['new_state_version'] == version, 'completion state version mismatch')
            if tid in started and started[tid][0]['proposal_id'] == pid:
                require(tid not in done, 'duplicate service completion')
                done[tid] = (e, i)
    require(not active and not before_start, 'unclosed physical trace')
    require(set(released) == set(tasks) and set(returned) == set(tasks), 'missing release/return')
    require(state == trace['final_state'] and version == trace['final_state_version'], 'final state mismatch')
    require(trace['event_count'] == len(trace['events']), 'event count mismatch')
    per_task = {}
    for tid, task in tasks.items():
        R, ri = released[tid]; P, pi = returned[tid]
        S = started[tid][0]['timestamp_ms'] if tid in started else None
        F = done[tid][0]['timestamp_ms'] if tid in done else None
        per_task[tid] = {'release_ms': R, 'deadline_ms': task['completion_deadline_ms'],
                         'proposal_return_ms': P, 'start_ms': S, 'completion_ms': F,
                         'started': S is not None, 'completed': F is not None,
                         'timely': F is not None and F <= task['completion_deadline_ms'],
                         'logical_proposal_return_ms': P - R,
                         'proposal_to_start_ms': S - P if S is not None else None,
                         'task_start_wait_ms': S - R if S is not None else None,
                         'execution_ms': F - S if F is not None else None,
                         'completion_latency_ms': F - R if F is not None else None,
                         'tardiness_ms': max(0, F - task['completion_deadline_ms']) if F is not None else None,
                         'event_indices': {'release': ri, 'return': pi, 'start': started[tid][1] if tid in started else None,
                                           'completion': done[tid][1] if tid in done else None},
                         'null_reasons': {'start': None if S is not None else 'not_started',
                                          'completion': None if F is not None else 'not_completed'},
                         'coordination_compute_ms': None, 'API_wallclock_ms': None,
                         'unobserved_reason': 'not_instrumented'}
    n, c, t = len(tasks), len(done), sum(r['timely'] for r in per_task.values())
    metrics = {'service_rate': c/n, 'timely_service_rate': t/n,
               'executed_capacity_violation_duration_ms': excess_ms, 'excess_resource_unit_ms': excess_integral,
               'whole_house_completion_ms': max(r['completion_ms'] for r in per_task.values()) - episode['episode_release_at_ms'] if c == n else None}
    for key in RUN_METRICS[2:]:
        event = {'reservation_count': 'action_reserved', 'actual_start_count': 'action_started'}.get(key, key.removesuffix('_count'))
        metrics[key] = counts[event]
    return {'required_task_ids': list(tasks), 'completed_task_ids': [tid for tid in tasks if tid in done],
            'denominators': {'required': n, 'completed': c, 'timely': t}, 'metrics': metrics,
            'auxiliary': {'conditional_timely_rate': t/c if c else None,
                          'conditional_timely_null_reason': None if c else 'no_completed_requests',
                          'own_completed_means': {m: sum(per_task[x][m] for x in done)/c if c else None for m in TIME_METRICS}},
            'all_completed': c == n, 'all_timely': t == n, 'tasks': per_task,
            'event_counts': dict(counts), 'affected_task_ids': {k: sorted(v) for k, v in affected.items()},
            'event_reason_counts': {k: dict(v) for k, v in reasons.items()},
            'physical_intervals': intervals, 'capacity_violation_intervals': safety_intervals,
            'preconditions_at_start': preconditions, 'invalid_precondition_start_count': sum(not p['valid'] for p in preconditions),
            'coordination_compute_ms': None, 'API_wallclock_ms': None, 'unobserved_reason': 'not_instrumented'}


def time_compare(rows, rules):
    E = rows[0]['required_task_ids']
    require(all(r['required_task_ids'] == E for r in rows), 'required populations differ')
    common = [t for t in E if all(t in r['completed_task_ids'] for r in rows)]
    result = {'required_task_ids': E, 'completed_task_ids_by_arm': [r['completed_task_ids'] for r in rows],
              'common_task_ids': common, 'coverage': len(common)/len(E), 'metrics': {}}
    for m in rules:
        require(all(m in r['tasks'][t] and r['tasks'][t][m] is not None for r in rows for t in common), 'missing metric on common population')
        vals = [sum(r['tasks'][t][m] for t in common)/len(common) if common else None for r in rows]
        result['metrics'][m] = {'arm_means': vals, 'value': vals[1]-vals[0] if len(rows) == 2 and common else
                                (vals[3]-vals[1])-(vals[2]-vals[0]) if len(rows) == 4 and common else None,
                                'null_reason': None if common else 'no_common_completed_requests',
                                'per_task_values': {t: [r['tasks'][t][m] for r in rows] for t in common}}
        if len(rows) == 4:
            result['metrics'][m]['effects_on_identical_K'] = {
                'capacity_effect_base': vals[2]-vals[0] if common else None,
                'capacity_effect_loose': vals[3]-vals[1] if common else None,
                'deadline_effect_tight': vals[1]-vals[0] if common else None,
                'deadline_effect_adequate': vals[3]-vals[2] if common else None,
            }
    return result


def compare_pair(pair, rows, rules):
    a, b = rows[pair['left']], rows[pair['right']]
    require(a['required_task_ids'] == b['required_task_ids'], 'pair E mismatch')
    scalar_names = rules['four_cell_allowlist']['fixed_E_rates'] + rules['four_cell_allowlist']['run_event_or_process'] + ['whole_house_completion_ms']
    return {**pair, 'scalar_deltas': {m: {'left': a['metrics'][m], 'right': b['metrics'][m],
              'value': b['metrics'][m]-a['metrics'][m] if a['metrics'][m] is not None and b['metrics'][m] is not None else None,
              'null_reason': None if a['metrics'][m] is not None and b['metrics'][m] is not None else 'not_all_required_completed_in_both_arms'} for m in scalar_names},
            'conditional_time': time_compare([a, b], rules['four_cell_allowlist']['same_four_cell_completed_population'])}


def compare_cells(group, rows, rules):
    rs = [rows[s] for s in group['slots']]; E = rs[0]['required_task_ids']
    population = analysis_population(E, {c: r['completed_task_ids'] for c, r in zip(CELL_ORDER, rs)})
    names = rules['four_cell_allowlist']['fixed_E_rates'] + rules['four_cell_allowlist']['run_event_or_process']
    scalars = {}
    for m in names + rules['four_cell_allowlist']['all_E_completed_in_all_four_cells']:
        vals = [r['metrics'][m] for r in rs]
        eligible = m != 'whole_house_completion_ms' or population['all_E_completed_in_all_four_cells']
        require(not eligible or all(v is not None for v in vals), 'missing eligible scalar')
        scalars[m] = {'cell_values': vals, 'interaction': (vals[3]-vals[1])-(vals[2]-vals[0]) if eligible else None,
                      'capacity_effect_base': vals[2]-vals[0] if eligible else None,
                      'capacity_effect_loose': vals[3]-vals[1] if eligible else None,
                      'deadline_effect_tight': vals[1]-vals[0] if eligible else None,
                      'deadline_effect_adequate': vals[3]-vals[2] if eligible else None,
                      'null_reason': None if eligible else 'not_all_required_completed_in_four_cells'}
    return {**group, 'population': population, 'scalar_effects': scalars,
            'conditional_time': time_compare(rs, rules['four_cell_allowlist']['same_four_cell_completed_population'])}


def macro(rows, configurations, rules):
    result = {}
    policies = sorted({r['policy'] for r in rows.values()})
    require(set(policies) == {'GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator'}, 'missing macro policy')
    bases = sorted({c['base_episode_id'] for c in configurations})
    require(len(bases) == 2, 'template count mismatch')
    cmap = {c['episode_id']: c for c in configurations}
    for policy in policies:
        templates = {}
        for base in bases:
            rs = [r for r in rows.values() if r['policy'] == policy and cmap[r['episode_id']]['base_episode_id'] == base]
            require(len(rs) == 12, 'missing macro slot; no reweighting')
            templates[base] = {'slot_weights': [{'slot_id': r['slot_id'], 'weight': '1/12', 'denominators': r['denominators']} for r in rs],
                               'rates': {m: sum(r['metrics'][m] for r in rs)/12 for m in rules['template_macro']['metrics']}}
        result[policy] = {'templates': templates, 'template_weight': '1/2',
                          'rates': {m: sum(x['rates'][m] for x in templates.values())/2 for m in rules['template_macro']['metrics']}}
    return result


def bundle(root=ROOT):
    require(digest(FREEZE, root) == FREEZE_SHA, 'freeze record changed')
    freeze = read(FREEZE, root)
    require(freeze['status'] == 'frozen_contract_only_adapter_not_accepted', 'contract not frozen')
    for path, sha in {**freeze['reviewed_sha256'], **freeze['source_sha256']}.items():
        require(digest(path, root) == sha, 'frozen hash mismatch: ' + path)
    plan = read(freeze['plan_path'], root); rules = plan['metric_rules']; docs = {}
    for config in plan['configurations']:
        docs[config['episode_id']] = read(config['source_path'], root)
    rows = {}
    for item in plan['runs']:
        require(item['slot_id'] not in rows, 'duplicate run slot')
        d = docs[item['episode_id']]
        r = d['runs'][int(item['source_pointer'].split('/')[-1])]
        require((r['episode_id'], r['policy'], r['arrival_order_index']) == (item['episode_id'], item['policy'], item['order']), 'run pointer mismatch')
        scored = recount(d['episode'], r)
        config = next(c for c in plan['configurations'] if c['episode_id'] == item['episode_id'])
        require(scored['required_task_ids'] == [t['task_id'] for t in config['required_requests']], 'static E mismatch')
        rows[item['slot_id']] = {**item, **scored}
    require(len(rows) == 72, 'missing run count')
    pairs = [compare_pair(p, rows, rules) for p in plan['pairs']]
    groups = [compare_cells(g, rows, rules) for g in plan['four_cells']]
    artifacts = {f'{OUT}/{eid}.json': {'episode_id': eid, 'status': 'author_result_pending_implementation_review',
                  'runs': [r for r in rows.values() if r['episode_id'] == eid]} for eid in docs}
    for kind in ('policy', 'capacity', 'deadline', 'return_order'):
        artifacts[f'{OUT}/pairs_{kind}.json'] = {'kind': kind, 'pairs': [p for p in pairs if p['kind'] == kind]}
    artifacts[f'{OUT}/four_cells.json'] = {'groups': groups}
    artifacts[f'{OUT}/summary.json'] = {'status': 'author_result_pending_implementation_review',
        'runs': len(rows), 'pairs': len(pairs), 'four_cells': len(groups),
        'template_macro': macro(rows, plan['configurations'], rules),
        'evidence': 'scripted_deterministic_replays_not_new_model_trials',
        'api_calls': 0, 'simulator_runs': 0, 'adapter_acceptance': None}
    artifacts[f'{OUT}/manifest.json'] = {'freeze_sha256': digest(FREEZE, root),
        'adapter_sha256': digest('homecoord_bench/task_revision/f1_aggregation_v1.py', root),
        'source_sha256': freeze['source_sha256'],
        'artifact_sha256': {p: hashlib.sha256(serialize(v).encode('utf-8')).hexdigest() for p, v in artifacts.items()},
        'implementation_acceptance': None, 'independent_dual_review_complete': False}
    return artifacts


def serialize(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + '\n'


if __name__ == '__main__':
    import sys
    data = bundle()
    if len(sys.argv) == 1:
        print(json.dumps(list(data)))
    else:
        text = serialize(data[sys.argv[1]])
        offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        print(json.dumps({'text': text[offset:offset+30000], 'next': offset+30000 if offset+30000 < len(text) else None}))
