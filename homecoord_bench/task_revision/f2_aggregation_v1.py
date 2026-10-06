"""Frozen F2 event/statistics adapter. No simulation, API or legacy score reuse."""
import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.f2_information import build_agent_request
from homecoord_bench.task_revision.f2_statistical_contract_v1 import ROOT, POLICIES
FREEZE = 'docs/f2_statistical_contract_v1_20261004/freeze_20261004.json'
FREEZE_SHA = '78d627277b11978ef7b69faf836a051f4c3b85ba8d8d998dcf4601ddcf3d748f'
OUT = 'docs/f2_aggregation_v1_20261004'
CELL_ORDER = ('tight_simultaneous','tight_late','adequate_simultaneous','adequate_late')
TIME_METRICS = ('task_start_wait_ms', 'proposal_to_start_ms', 'execution_ms',
                'completion_latency_ms', 'tardiness_ms')

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
    require(run['evaluation_episode_id'] == episode['episode_id'], 'episode identity mismatch')
    trace = run['trace']
    require(trace['episode_id'] == episode['episode_id'] and trace['policy'] == run['policy'], 'trace identity mismatch')
    require(not episode.get('constraints'), 'outside F2 scope')
    state = deepcopy(episode['initial_state']['values']); version = episode['initial_state']['version']
    calls, proposals = {}, {}
    agents = {a['agent_id']: a for a in episode['agents']}
    for call in run['calls']:
        r = call['request']; tid = r['task']['task_id']
        require(tid in tasks and tid not in calls, 'duplicate/unknown call task')
        require(r['episode_id'] == r['base_episode_id'] == 'F2-public-home' and r['architecture'] == run['policy'], 'call scope mismatch')
        require(r['current_time_ms'] == tasks[tid]['release_at_ms'], 'call release mismatch')
        agent = agents[tasks[tid]['agent_id']]
        require(r['agent']['agent_id'] == agent['agent_id'] and r['allowed_tools'] == agent['tools'], 'call permission mismatch')
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
    last = 0; excess_ms = 0; excess_integral = 0; seen_external = set()
    capacity = episode['home']['resources']['max_power_kw']
    allowed_events = {'task_released', 'proposal_returned', 'coordination_decision', 'action_reserved',
                      'action_started', 'action_completed', 'action_rejected', 'retry_queued', 'retry_scheduled', 'state_update'}
    for i, e in enumerate(trace['events']):
        kind, now, tid = e['type'], e['timestamp_ms'], e.get('task_id')
        require(kind in allowed_events and type(now) is int and now >= last, 'unknown/nonmonotonic event')
        require(tid in tasks or kind == 'state_update' and e.get('source') != 'action_started', 'unknown event task')
        units = sum(s['power_kw'] for s, _ in active.values())
        if now > last and units > capacity:
            excess_ms += now - last; excess_integral += (now - last) * (units - capacity)
            safety_intervals.append({'start_ms': last, 'end_ms': now, 'load_units': units,
                                     'capacity_units': capacity, 'next_event_index': i})
        last = now
        counts[kind] += 1
        if tid is not None: affected[kind].add(tid)
        if 'reason' in e:
            reasons[kind][str(e['reason'])] += 1
        if kind == 'task_released':
            require(tid not in released and now == tasks[tid]['release_at_ms'], 'release identity/time mismatch')
            require(e['request_id'] == calls[tid]['request']['request_id'], 'release request mismatch')
            expected_request = build_agent_request(episode, agents[tasks[tid]['agent_id']], tasks[tid],
                architecture=run['policy'], current_time_ms=now, current_state=state, state_version=version)
            require(expected_request == calls[tid]['request'], 'complete public request/state mismatch')
            released[tid] = (now, i)
        elif kind == 'proposal_returned':
            require(tid in released and tid not in returned, 'invalid return lifecycle')
            require(e['request_id'] == calls[tid]['request']['request_id'] and e['response_type'] == 'action_proposal', 'return request mismatch')
            require(now - released[tid][0] == e['latency_ms'] == 300, 'return offset mismatch')
            returned[tid] = (now, i)
        elif kind in ('action_reserved', 'coordination_decision', 'action_rejected'):
            pid = e['proposal_id']
            require(pid in proposals and proposals[pid][0] == tid and tid in returned, 'unknown event proposal')
            if kind == 'coordination_decision':
                require(e['decision'] in ('accept', 'defer', 'reject'), 'unknown coordination decision')
                key = 'coordination_' + e['decision']
                counts[key] += 1; affected[key].add(tid)
        elif kind == 'state_update':
            if e.get('source') != 'action_started':
                matches = [j for j, event in enumerate(episode['exogenous_events'])
                           if event['at_ms'] == now and event['patch'] == e['patch'] and event['event'] == e['source']]
                require(len(matches) == 1 and matches[0] not in seen_external, 'external update mismatch')
                seen_external.add(matches[0])
                for path, val in e['patch'].items(): put(state, path, val)
                version += 1
                require(e['new_state_version'] == version, 'external state version mismatch')
                continue
            require(tid not in before_start, 'unexpected state update')
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
                require(tid not in started, 'multiple service attempts outside F2 scope')
                started[tid] = (e, i)
        elif kind == 'action_completed':
            pid = e['proposal_id']
            require(pid in active, 'unmatched completion receipt')
            start, si = active.pop(pid)
            require(all(e[k] == start[k] for k in ('task_id', 'agent_id', 'target', 'operation')), 'receipt identity mismatch')
            require(now == start['timestamp_ms'] + start['duration_ms'] and e['effects'] == start['completion_effects'], 'receipt time/effects mismatch')
            intervals.append({'task_id': tid, 'proposal_id': pid, 'start_event_index': si, 'completion_event_index': i,
                              'start_ms': start['timestamp_ms'], 'end_ms': now, 'units': start['power_kw'], 'operation': start['operation']})
            for path, val in e['effects'].items(): put(state, path, val)
            version += 1
            require(e['new_state_version'] == version, 'completion state version mismatch')
            if tid in started and started[tid][0]['proposal_id'] == pid:
                require(tid not in done, 'duplicate service completion')
                done[tid] = (e, i)
    require(not active and not before_start, 'unclosed physical trace')
    require(seen_external == set(range(len(episode['exogenous_events']))), 'missing external publication update')
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
    for key in ('coordination_defer_count', 'action_rejected_count', 'retry_queued_count', 'retry_scheduled_count'):
        event = {'reservation_count': 'action_reserved', 'actual_start_count': 'action_started'}.get(key, key.removesuffix('_count'))
        metrics[key] = counts[event]
    subsets = {'early': [tid for tid,t in tasks.items() if tid != 'water' and t['release_at_ms']==0], 'water': ['water']}
    require(len(subsets['early'])==3 and 'water' in tasks, 'fixed subsets mismatch')
    layered = {}
    for name, ids in subsets.items():
        nc = sum(per_task[t]['completed'] for t in ids); nt = sum(per_task[t]['timely'] for t in ids)
        layered[name] = {'required_task_ids': ids, 'denominators': {'required':len(ids), 'completed':nc, 'timely':nt},
                         'service_rate':nc/len(ids), 'timely_service_rate':nt/len(ids)}
    return {'subsets':layered, 'arrival_background': arrival_background(episode, run, intervals, per_task),
            'required_task_ids': list(tasks), 'completed_task_ids': [tid for tid in tasks if tid in done],
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


def arrival_background(episode, run, intervals, tasks):
    L = tasks['water']['release_ms']
    if L == 0: return None
    early = [tid for tid in tasks if tid != 'water']
    crossing = [{**p, 'remaining_ms':p['end_ms']-L} for p in intervals
                if p['task_id'] in early and p['operation']=='prepare' and p['start_ms']<L<p['end_ms']]
    events=run['trace']['events']; reservations=[]
    for i,x in enumerate(events):
        if x['type']!='action_reserved' or not x['timestamp_ms']<L<x['scheduled_start_ms']: continue
        pid=x['proposal_id']
        outcomes=[(j,e) for j,e in enumerate(events) if j>i and e['type'] in ('action_started','action_rejected')
                  and e.get('proposal_id')==pid and e['timestamp_ms']==x['scheduled_start_ms']]
        require(len(outcomes)==1, 'ambiguous future reservation outcome')
        starts=[(j,e) for j,e in enumerate(events) if j>i and e['type']=='action_started' and e.get('proposal_id')==pid]
        require(len(starts)<=1, 'ambiguous reservation actual start')
        j,e=outcomes[0]
        reservations.append({'task_id':x['task_id'],'proposal_id':pid,'reservation_event_index':i,
             'reserved_ms':x['timestamp_ms'],'planned_start_ms':x['scheduled_start_ms'],
             'scheduled_disposition_event_index':j,'scheduled_disposition':e['type'],
             'actual_start_ms':starts[0][1]['timestamp_ms'] if starts else None,
             'actual_start_event_index':starts[0][0] if starts else None,
             'counts_as_physical_load_at_L':False})
    water_events={kind: next(({'event_index':i,'timestamp_ms':e['timestamp_ms']} for i,e in enumerate(events)
                    if e.get('task_id')=='water' and e['type']==kind and e['timestamp_ms']>=L), None)
                  for kind in ('task_released','proposal_returned','action_started','action_completed','action_rejected','retry_queued','retry_scheduled')}
    return {'release_ms':L,'interpretation':'descriptive_resource_background_not_causal_or_unavoidable',
            'early_history':[{'task_id':tid,'start_ms':tasks[tid]['start_ms'],'end_ms':tasks[tid]['completion_ms'],
                              'started_before_L':tasks[tid]['start_ms'] is not None and tasks[tid]['start_ms']<L,
                              'event_indices':tasks[tid]['event_indices']} for tid in early],
            'crossing_actual_intervals':crossing,'physical_units_crossing_L':sum(p['units'] for p in crossing),
            'capacity_units':episode['home']['resources']['max_power_kw'],
            'water_required_units':next(g['power_kw'] for g in episode['action_grounding'] if g['task_id']=='water' and g['operation']=='prepare'),
            'future_reservations_created_before_L':reservations,'first_water_events':water_events}


def effects(vals):
    if len(vals)==2: return {'right_minus_left':vals[1]-vals[0]}
    require(len(vals)==4,'invalid comparison arity')
    return {'capacity_effect_simultaneous':vals[2]-vals[0], 'capacity_effect_late':vals[3]-vals[1],
            'release_effect_tight':vals[1]-vals[0], 'release_effect_adequate':vals[3]-vals[2],
            'interaction':(vals[3]-vals[1])-(vals[2]-vals[0])}


def time_compare(rows, names, subset=None):
    E=rows[0]['required_task_ids']
    require(all(r['required_task_ids']==E for r in rows),'comparison E mismatch')
    if subset is not None:
        require(set(subset)<=set(E),'unknown fixed subset'); E=[t for t in E if t in subset]
    require(bool(E),'empty fixed subset')
    K=[t for t in E if all(t in r['completed_task_ids'] for r in rows)]
    result={'required_task_ids':E,'completed_task_ids_by_arm':[[t for t in E if t in r['completed_task_ids']] for r in rows],
            'common_task_ids':K,'common_count':len(K),'required_count':len(E),'coverage':len(K)/len(E),
            'excluded_tasks':[{'task_id':t,'not_completed_arm_indices':[i for i,r in enumerate(rows) if t not in r['completed_task_ids']]} for t in E if t not in K],
            'eligible':bool(K),'null_reason':None if K else 'no_common_completed_requests','metrics':{}}
    for m in names:
        require(all(m in r['tasks'][t] and r['tasks'][t][m] is not None for r in rows for t in K),'missing metric on K')
        vals=[sum(r['tasks'][t][m] for t in K)/len(K) if K else None for r in rows]
        result['metrics'][m]={'arm_means':vals,'effects':effects(vals) if K else {k:None for k in effects([0]*len(rows))},
                             'null_reason':None if K else 'no_common_completed_requests',
                             'per_task_values':{t:[r['tasks'][t][m] for r in rows] for t in K}}
    return result


def compare(spec, rows, rules, four=False):
    ids=spec['slots'] if four else [spec['left'],spec['right']]
    require(len(ids)==(4 if four else 2) and all(s in rows for s in ids),'missing comparison slot')
    rs=[rows[s] for s in ids]; E=rs[0]['required_task_ids']
    require(all(r['required_task_ids']==E for r in rs),'comparison E mismatch')
    scalar={}
    for m in rules['primary_rates']+rules['process_allowlist']+['whole_house_completion_ms']:
        vals=[r['metrics'][m] for r in rs]
        eligible=m!='whole_house_completion_ms' or all(r['all_completed'] for r in rs)
        require(not eligible or all(v is not None for v in vals),'missing eligible scalar')
        scalar[m]={'arm_values':vals,'effects':effects(vals) if eligible else {k:None for k in effects([0]*len(rs))},
                   'null_reason':None if eligible else ('not_all_required_completed_in_four_cells' if four else 'not_all_required_completed_in_both_arms')}
    subset_rates={}
    for name in ('early','water'):
        fixed=rs[0]['subsets'][name]['required_task_ids']
        require(all(r['subsets'][name]['required_task_ids']==fixed for r in rs),'subset population mismatch')
        subset_rates[name]={'required_task_ids':fixed,'denominators_by_arm':[r['subsets'][name]['denominators'] for r in rs],
                           'rates':{m:{'arm_values':[r['subsets'][name][m] for r in rs],
                                       'effects':effects([r['subsets'][name][m] for r in rs])} for m in rules['primary_rates']}}
    return {**spec,'scalar_comparison':scalar,'fixed_subset_service':subset_rates,
            'conditional_time':time_compare(rs,rules['time_allowlist']),
            'conditional_subset_time':{name:time_compare(rs,rules['time_allowlist'],rs[0]['subsets'][name]['required_task_ids']) for name in ('early','water')},
            'whole_house_clock_note':'global_schedule_span_not_own_release_response_or_future_information_value'}


def first_diff(a,b,path=''):
    if type(a)!=type(b): return path
    if isinstance(a,dict):
        if set(a)!=set(b):return path+'/keys'
        for k in a:
            d=first_diff(a[k],b[k],path+'/'+str(k))
            if d is not None:return d
        return None
    if isinstance(a,list):
        if len(a)!=len(b):return path+'/length'
        for i,(x,y) in enumerate(zip(a,b)):
            d=first_diff(x,y,path+'/'+str(i))
            if d is not None:return d
        return None
    return None if a==b else path


def prefix_check(main, diagnostic, cutoff):
    def prefix(r):
        ci=[i for i,c in enumerate(r['calls']) if c['request']['current_time_ms']<cutoff]
        ei=[i for i,e in enumerate(r['trace']['events']) if e['timestamp_ms']<cutoff]
        return {'calls':[r['calls'][i] for i in ci],'events':[r['trace']['events'][i] for i in ei]}, {'calls':ci,'events':ei}
    a,ai=prefix(main); b,bi=prefix(diagnostic); diff=first_diff(a,b)
    return {'before_ms':cutoff,'equal':diff is None,'first_difference_channel':diff,
            'main_prefix_indices':ai,'diagnostic_prefix_indices':bi,'performance_comparison':False}


def macro(rows, configurations):
    require(len(rows)==32 and {r['policy'] for r in rows.values()}==set(POLICIES),'missing macro rows/policy')
    config={c['episode_id']:c for c in configurations}; result={}
    for policy in POLICIES:
        templates={}
        for base in ('D-F2-01','D-F2-02'):
            rs=[r for r in rows.values() if r['policy']==policy and config[r['episode_id']]['base_episode_id']==base]
            require(len(rs)==4,'missing macro slot; do not reweight')
            templates[base]={'slot_weights':[{'slot_id':r['slot_id'],'weight':'1/4','denominators':r['denominators']} for r in rs],
                             'rates':{m:sum(r['metrics'][m] for r in rs)/4 for m in ('service_rate','timely_service_rate')}}
        result[policy]={'templates':templates,'template_weight':'1/2',
                        'rates':{m:sum(t['rates'][m] for t in templates.values())/2 for m in ('service_rate','timely_service_rate')}}
    return result


def bundle(root=ROOT):
    require(digest(FREEZE,root)==FREEZE_SHA,'freeze record changed')
    freeze=read(FREEZE,root)
    require(freeze['status']=='frozen_contract_only_adapter_not_accepted','contract not frozen')
    for path,sha in {**freeze['reviewed_sha256'],**freeze['source_sha256'],**freeze['runtime_source_sha256']}.items():
        require(digest(path,root)==sha,'hash mismatch: '+path)
    plan=read(freeze['plan_path'],root); rules=plan['metric_rules']
    source='homecoord_bench/task_revision/fixtures/f2_v7'
    inputs=read(source+'/inputs.json',root)['episodes']; episodes={e['episode_id']:e for e in inputs}
    main_docs={c['episode_id']:read(c['source_path'],root) for c in plan['configurations']}
    configs={c['episode_id']:c for c in plan['configurations']}
    rows={}; raw={}
    for item in plan['runs']:
        sid=item['slot_id']; require(sid not in rows,'duplicate main slot')
        r=main_docs[item['episode_id']]['runs'][int(item['source_pointer'].split('/')[-1])]
        require((r['evaluation_episode_id'],r['policy'])==(item['episode_id'],item['policy']),'main pointer mismatch')
        raw[sid]=r
        scored=recount(episodes[item['episode_id']],r)
        c=configs[item['episode_id']]
        require(scored['required_task_ids']==[t['task_id'] for t in c['required_requests']],'static E mismatch')
        require(scored['subsets']['early']['required_task_ids']==c['early_task_ids'],'static early subset mismatch')
        rows[sid]={**item,**scored}
    require(len(rows)==32,'main scope mismatch')
    pairs=[compare(p,rows,rules) for p in plan['pairs']]
    cells=[compare(g,rows,rules,True) for g in plan['four_cells']]
    diagnostics={}; diagnostic_items={r['slot_id']:r for r in plan['diagnostic_runs']}; diagnostic_results=[]
    for p in plan['diagnostic_prefix_pairs']:
        item=diagnostic_items[p['diagnostic_slot']]; path=item['source_path']
        if path not in diagnostics: diagnostics[path]=read(path,root)
        d=diagnostics[path]['runs'][int(item['source_pointer'].split('/')[-1])]
        require(d['policy']==item['policy'],'diagnostic pointer mismatch')
        diagnostic_results.append({**p,**prefix_check(raw[p['main_slot']],d,p['before_ms']),
                                    'diagnostic_source_path':path,'diagnostic_source_pointer':item['source_pointer']})
    require(len(pairs)==72 and len(cells)==8 and len(diagnostic_results)==48,'comparison scope mismatch')
    artifacts={f'{OUT}/{eid}.json':{'episode_id':eid,'status':'author_result_pending_implementation_review',
                                   'runs':[r for r in rows.values() if r['episode_id']==eid]} for eid in configs}
    for kind in ('policy','strong_rule','capacity','release'):
        artifacts[f'{OUT}/pairs_{kind}.json']={'kind':kind,'pairs':[p for p in pairs if p['kind']==kind]}
    artifacts[f'{OUT}/four_cells.json']={'groups':cells}
    artifacts[f'{OUT}/information_diagnostics.json']={'scope':'prefix_only_not_service_scores','pairs':diagnostic_results}
    artifacts[f'{OUT}/summary.json']={'status':'author_result_pending_implementation_review','runs':32,'pairs':72,'four_cells':8,
                                     'diagnostic_prefix_pairs':48,'template_macro':macro(rows,plan['configurations']),
                                     'api_calls':0,'simulator_runs':0,'adapter_acceptance':None}
    artifacts[f'{OUT}/manifest.json']={'freeze_sha256':digest(FREEZE,root),
        'adapter_sha256':digest('homecoord_bench/task_revision/f2_aggregation_v1.py',root),
        'source_sha256':freeze['source_sha256'],
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in artifacts.items()},
        'implementation_acceptance':None,'independent_dual_review_complete':False}
    return artifacts


def serialize(obj):return json.dumps(obj,ensure_ascii=False,indent=2)+'\n'


if __name__=='__main__':
    import sys
    data=bundle()
    if len(sys.argv)==1:print(json.dumps(list(data)))
    else:
        text=serialize(data[sys.argv[1]]);offset=int(sys.argv[2]) if len(sys.argv)>2 else 0
        print(json.dumps({'text':text[offset:offset+40000],'next':offset+40000 if offset+40000<len(text) else None}))
