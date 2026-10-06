"""Independent replay/audit for lifecycle v2; no simulator aggregate reuse."""
from copy import deepcopy
from evaluate import constraints_hold, get_path, set_path


def withdrawal_required(e, trace):
    """Offline disposition oracle uses actual events, never predicts arrivals."""
    contracts = e['simulation'].get('lifecycle_contracts', {})
    expected = {tid: None for tid,c in contracts.items() if c['mode']=='withdraw'}
    finish = {tid: min((x['timestamp_ms'] for x in trace['events'] if x['type']=='action_completed'
                       and x['task_id']==tid),default=float('inf')) for tid in expected}
    state = deepcopy(e['initial_state']['values'])
    released = set()
    for x in trace['events']:
        if x['type']=='task_released':
            released.add(x['task_id'])
        patch = x.get('patch',{}) if x['type']=='state_update' else x.get('effects',{}) if x['type']=='action_completed' else {}
        for path,value in patch.items():
            set_path(state,path,value)
        for tid in expected:
            if (expected[tid] is None and tid in released and x['timestamp_ms'] < finish[tid]
                    and any(get_path(state,r['path']) != r['value'] for r in contracts[tid]['valid_when'])):
                expected[tid] = x['timestamp_ms']
    return expected


def metrics(e, trace, result):
    events = trace['events']
    completed = result['task_correct_action_completed']
    contracts = e['simulation'].get('lifecycle_contracts', {})
    needs_withdrawal = withdrawal_required(e,trace)
    resolution, recovery = {}, {}
    for tid, c in contracts.items():
        withdrawals = [x for x in events if x['type'] == 'task_withdrawn' and x['task_id'] == tid]
        repairs = [x for x in events if x['type'] == 'restart_proposed' and x['task_id'] == tid]
        if needs_withdrawal.get(tid) is not None:
            resolution[tid] = bool(withdrawals and withdrawals[0]['timestamp_ms']==needs_withdrawal[tid]
                                  and not any(x['type'] == 'action_completed' and x['task_id'] == tid
                                              and x['timestamp_ms'] >= needs_withdrawal[tid] for x in events))
        else:
            resolution[tid] = completed[tid]
        recovery[tid] = completed[tid] if repairs or tid in result.get('waiting_recovery_task_ids', []) else None
    stops = {x['proposal_id']: x['timestamp_ms'] for x in events if x['type'] == 'action_stopped'}
    return {'action_completed': deepcopy(completed), 'resolution_correct': resolution,
            'recovery_completed': recovery,
            'completion_latency_ms': result['task_completion_latency_ms'],
            'completion_tardiness_ms': result['task_completion_tardiness_ms'],
            'harm_duration_ms': result['state_constraint_violation_duration_ms'],
            'zero_harm': result['state_constraint_violation_duration_ms'] == 0,
            'stop_latency_ms': {x['proposal_id']: stops[x['proposal_id']] - x['timestamp_ms']
                                if x['proposal_id'] in stops else None for x in events if x['type'] == 'stop_requested'},
            'stop_confirmed_count': len(stops),
            'stop_ack_too_late_count': result.get('stop_ack_too_late_count', 0),
            'restart_count': result.get('restart_count', 0),
            'active_reservations_at_end': result.get('active_reservations_at_end', 0)}


def audit(e, trace, reported):
    state = deepcopy(e['initial_state']['values'])
    tasks = {t['task_id']: t for t in e['task_stream']}
    active, reservations, cancelled, completed, requested = {}, set(), set(), set(), {}
    completion_at, stops_at, withdrawn_at = {}, {}, {}
    contracts = e['simulation'].get('lifecycle_contracts', {})
    clock, harm = e['episode_release_at_ms'], 0
    for x in trace['events']:
        now, kind = x['timestamp_ms'], x['type']
        assert now >= clock
        if not constraints_hold(state, e['constraints']):
            harm += now - clock
        clock = now
        if kind == 'action_reserved':
            assert x['proposal_id'] not in reservations
            reservations.add(x['proposal_id'])
        elif kind == 'action_rejected':
            reservations.discard(x['proposal_id'])
        elif kind == 'action_started':
            assert x['proposal_id'] in reservations and x['proposal_id'] not in active
            assert now >= tasks[x['task_id']]['release_at_ms']
            assert all(get_path(state, r['path']) == r['value'] for r in x['requires'])
            ground = next(g for g in e['action_grounding'] if g['task_id'] == x['task_id'])
            assert x['duration_ms'] == ground['duration_ms']
            assert (x['target'], x['operation'], x['agent_id']) == (ground['target'], ground['operation'], ground['agent_id'])
            active[x['proposal_id']] = x
        elif kind == 'task_withdrawn':
            c = contracts[x['task_id']]
            assert c['mode'] == 'withdraw' and x['task_id'] not in withdrawn_at
            assert any(get_path(state,r['path']) != r['value'] for r in c['valid_when'])
            assert now >= tasks[x['task_id']]['release_at_ms']
            withdrawn_at[x['task_id']] = now
        elif kind == 'restart_proposed':
            c = contracts[x['task_id']]
            assert c['mode'] == 'restart_from_zero' and x['task_id'] not in withdrawn_at
            assert all(get_path(state,r['path']) == r['value'] for r in c['valid_when'])
            assert not any(a['task_id'] == x['task_id'] for a in active.values())
            assert x['additional_model_calls'] == 0
        elif kind == 'stop_requested':
            assert x['proposal_id'] in active and x['proposal_id'] not in requested
            contract = e['simulation']['lifecycle_contracts'][x['task_id']]
            assert any(get_path(state,r['path']) != r['value'] for r in contract['valid_when'])
            assert x['ack_due_ms'] == now + contract['stop_ack_delay_ms']
            requested[x['proposal_id']] = x
        elif kind == 'action_stopped':
            start = active.pop(x['proposal_id'])
            assert x['proposal_id'] in requested
            assert now == requested[x['proposal_id']]['ack_due_ms']
            assert x['actual_runtime_ms'] == now - start['timestamp_ms']
            cancelled.add(x['proposal_id'])
            stops_at[x['proposal_id']] = now
        elif kind == 'reservation_released':
            assert x['proposal_id'] in cancelled
            reservations.remove(x['proposal_id'])
        elif kind == 'completion_discarded':
            assert x['proposal_id'] in cancelled and x['proposal_id'] not in active
        elif kind == 'action_completed':
            assert x['proposal_id'] not in cancelled
            start = active.pop(x['proposal_id'])
            assert now == start['timestamp_ms'] + start['duration_ms']
            ground = next(g for g in e['action_grounding'] if g['task_id'] == x['task_id'])
            assert x['effects'] == ground['completion_effects']
            completed.add(x['task_id'])
            completion_at.setdefault(x['task_id'],now)
            reservations.remove(x['proposal_id'])
        patch = x.get('patch', {}) if kind == 'state_update' else x.get('effects', {}) if kind == 'action_completed' else {}
        if kind == 'state_update' and x.get('source') == 'stop_ack':
            assert x['proposal_id'] in requested
            assert now == requested[x['proposal_id']]['ack_due_ms']
            assert patch == e['simulation']['lifecycle_contracts'][x['task_id']]['stop_effects']
        elif kind == 'state_update' and x.get('source') == 'action_started':
            ground = next(g for g in e['action_grounding'] if g['task_id'] == x['task_id'])
            assert patch == ground['start_effects']
        elif kind == 'state_update':
            assert any(event['at_ms'] == now and event.get('patch',{}) == patch
                       for event in e.get('exogenous_events', []))
        for path, value in patch.items():
            set_path(state, path, value)
    assert state == trace['final_state'] and not active and not reservations
    assert harm == reported['harm_duration_ms']
    assert {tid: tid in completed for tid in tasks} == reported['action_completed']
    assert len(cancelled) == reported['stop_confirmed_count']
    assert {tid: completion_at[tid]-t['release_at_ms'] if tid in completion_at else None
            for tid,t in tasks.items()} == reported['completion_latency_ms']
    assert {tid: max(0, completion_at[tid]-t['completion_deadline_ms'])
            if tid in completion_at and t.get('completion_deadline_ms') is not None else None
            for tid,t in tasks.items()} == reported['completion_tardiness_ms']
    assert {pid: stops_at[pid]-x['timestamp_ms'] if pid in stops_at else None
            for pid,x in requested.items()} == reported['stop_latency_ms']
    required = withdrawal_required(e,trace)
    assert {tid: bool(tid in withdrawn_at and withdrawn_at[tid]==required[tid]
                     and not any(x['type']=='action_completed' and x['task_id']==tid
                                 and x['timestamp_ms']>=required[tid] for x in trace['events']))
            if required.get(tid) is not None else tid in completed for tid in contracts} == reported['resolution_correct']
    return {'state_replay': 'passed', 'completion_and_cancellation_recount': 'passed',
            'reservation_release': 'passed', 'harm_integral_ms': harm}
