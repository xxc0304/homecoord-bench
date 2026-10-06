"""Independent C4 event reconstruction: actual stage, exposure and disposition."""
from copy import deepcopy
from evaluate import constraints_hold,get_path,set_path


def audit(e,trace,result,calls):
    tasks={t['task_id']:t for t in e['task_stream']};contracts=e['simulation']['lifecycle_contracts']
    primary=e['task_stream'][0]['task_id'];signal=contracts[primary]['valid_when'][0]['path']
    state=deepcopy(e['initial_state']['values']);version=e['initial_state']['version'];clock=0;harm=0
    active={};starts={};done={};cancelled=set();withdrawn={};expected_withdrawn=set();requests={};terminated={}
    onsets={};exposure={};reference={};excess={};phases=[];intervals=[];physical_after_withdrawal=[];physical_after_invalidation=[]
    dependency_waiting=set();dependency_blocked=set()
    assert trace['agent_requests']==[c['request'] for c in calls]
    for r in trace['agent_requests']:
        assert r['current_time_ms']==tasks[r['task']['task_id']]['release_at_ms']
        assert r['episode_id'] in ('HC-M12',)
        assert not {'action_template','required_action','acceptable_actions'}&set(r['task'])
    for idx,x in enumerate(trace['events']):
        now=x['timestamp_ms'];assert now>=clock
        if not constraints_hold(state,e['constraints']):harm+=now-clock
        for pid,s in active.items():
            if s['task_id'] not in contracts:continue
            invalid=any(get_path(state,r['path'])!=r['value'] for r in contracts[s['task_id']]['valid_when'])
            if invalid and now>clock:
                exposure[pid]=exposure.get(pid,0)+now-clock
                onset=onsets[pid];bound=onset+e['response_contract']['reference_ack_delay_ms']
                reference[pid]=reference.get(pid,0)+max(0,min(now,bound)-clock)
                limit=onset+e['response_contract']['quiescence_tolerance_ms']
                excess[pid]=excess.get(pid,0)+max(0,now-max(clock,limit))
        clock=now;tid=x.get('task_id');kind=x['type']
        if kind=='dependency_waiting':dependency_waiting.add(tid)
        if kind=='dependency_ready':
            assert all(d in done and d not in withdrawn for d in tasks[tid]['depends_on'])
            dependency_waiting.discard(tid)
        if kind=='dependency_blocked':
            assert any(d in withdrawn or d in dependency_blocked for d in tasks[tid]['depends_on'])
            dependency_waiting.discard(tid);dependency_blocked.add(tid)
        if kind=='state_update' and x.get('source') not in ('action_started','stop_ack'):
            patch=x['patch']
            if patch.get(signal) is False:
                live=next((s for s in active.values() if s['task_id']==primary),None)
                if primary in done:stage='after_service_completion'
                elif live and now==live['timestamp_ms']+live['duration_ms']:stage='natural_completion_boundary'
                elif live:
                    fraction=(now-live['timestamp_ms'])/live['duration_ms']
                    stage='running_early' if fraction<1/3 else 'running_mid' if fraction<2/3 else 'running_late'
                else:stage='before_release' if now<tasks[primary]['release_at_ms'] else 'released_not_started'
                phases.append({'event_index':idx,'timestamp_ms':now,'actual_stage':stage,'nominal_window':e['nominal_window']})
            elif x.get('source')=='challenge_unrelated':
                phases.append({'event_index':idx,'timestamp_ms':now,'actual_stage':'unrelated_update','nominal_window':e['nominal_window']})
        if kind=='task_withdrawn':
            assert tid not in withdrawn and contracts[tid]['mode']=='withdraw';withdrawn[tid]=now
        if kind=='action_started':
            assert tid not in withdrawn and x['proposal_id'] not in active
            for predecessor in tasks[tid].get('depends_on',[]):
                assert predecessor in done and predecessor not in withdrawn, 'missing trusted valid predecessor receipt'
                assert e['batch_binding'][predecessor]==e['batch_binding'][tid]
            assert now>=tasks[tid]['release_at_ms']
            assert all(get_path(state,r['path'])==r['value'] for r in x['requires'])
            g=next(g for g in e['action_grounding'] if g['task_id']==tid)
            assert (x['target'],x['operation'],x['duration_ms'],x['power_kw'])==(g['target'],g['operation'],g['duration_ms'],g['power_kw'])
            assert sum(s['power_kw'] for s in active.values())+x['power_kw']<=e['home']['resources']['max_power_kw']
            active[x['proposal_id']]=x;starts.setdefault(tid,now)
        if kind=='stop_requested':
            pid=x['proposal_id'];assert pid in active and pid in onsets and pid not in requests
            assert x['ack_due_ms']==now+contracts[tid]['stop_ack_delay_ms'];requests[pid]=x
        if kind=='attempt_invalidated':
            pid=x['proposal_id']
            assert pid in active and contracts[tid]['mode'] in ('restart_from_zero','withdraw') and onsets[pid]==now
        if kind in ('action_stopped','action_completed','withdrawn_action_physically_completed','invalidated_action_physically_completed'):
            pid=x['proposal_id'];s=active.pop(pid)
            assert s['task_id']==tid
            if kind=='action_stopped':
                assert now==requests[pid]['ack_due_ms'] and x['actual_runtime_ms']==now-s['timestamp_ms']
                cancelled.add(pid)
            else:
                assert pid not in cancelled and now==s['timestamp_ms']+s['duration_ms']
                g=next(g for g in e['action_grounding'] if g['task_id']==tid)
                effects=g['completion_effects']
                if kind=='withdrawn_action_physically_completed':
                    assert tid in withdrawn and now>=withdrawn[tid]
                    effects={p:v for p,v in effects.items() if p.startswith('devices.')}
                    physical_after_withdrawal.append({'task_id':tid,'proposal_id':pid,'timestamp_ms':now})
                elif kind=='invalidated_action_physically_completed':
                    assert pid in onsets and onsets[pid]<now
                    effects={p:v for p,v in effects.items() if p.startswith('devices.')}
                    physical_after_invalidation.append({'task_id':tid,'proposal_id':pid,'timestamp_ms':now,'invalid_since_ms':onsets[pid]})
                else:
                    assert tid not in withdrawn and pid not in onsets, 'invalid attempt cannot satisfy service'
                    done[tid]=now
                assert x['effects']==effects
            terminated[pid]={'timestamp_ms':now,'reason':kind}
            intervals.append({'task_id':tid,'proposal_id':pid,'start_ms':s['timestamp_ms'],'end_ms':now,'units':s['power_kw']})
        if kind=='completion_discarded':assert x['proposal_id'] in cancelled
        if kind=='restart_proposed':
            assert tid not in withdrawn and x['additional_model_calls']==0
        if kind=='state_update':
            patch=x['patch'];source=x['source']
            if source=='stop_ack':assert patch==contracts[tid]['stop_effects']
            elif source=='action_started':assert any(g['task_id']==tid and g['start_effects']==patch for g in e['action_grounding'])
            else:assert any(event['at_ms']==now and event['patch']==patch for event in e['exogenous_events'])
        elif kind in ('action_completed','withdrawn_action_physically_completed','invalidated_action_physically_completed'):patch=x['effects']
        else:patch={}
        for p,v in patch.items():set_path(state,p,v)
        if kind in ('state_update','action_completed','withdrawn_action_physically_completed','invalidated_action_physically_completed'):
            version+=1;assert x['new_state_version']==version
        for pid,s in active.items():
            if s['task_id'] in contracts and now<s['timestamp_ms']+s['duration_ms'] and any(
                    get_path(state,r['path'])!=r['value'] for r in contracts[s['task_id']]['valid_when']):onsets.setdefault(pid,now)
        for ct,c in contracts.items():
            live=next((s for s in active.values() if s['task_id']==ct),None)
            natural_boundary=live and now>=live['timestamp_ms']+live['duration_ms']
            if c['mode']=='withdraw' and now>=tasks[ct]['release_at_ms'] and ct not in done and not natural_boundary and any(
                    get_path(state,r['path'])!=r['value'] for r in c['valid_when']):expected_withdrawn.add(ct)
    assert not active and state==trace['final_state'] and version==trace['final_state_version']
    assert expected_withdrawn==set(withdrawn)==set(result['withdrawn_task_ids'])
    assert set(done)==set(result['dependency_completed_receipts'])
    assert dependency_waiting==set(result['dependency_waiting_task_ids'])
    assert dependency_blocked==set(result['dependency_blocked_task_ids'])
    assert harm==result['state_constraint_violation_duration_ms']
    metrics={'task_correct_action_completed':{tid:tid in done for tid in tasks},
             'task_start_wait_ms':{tid:starts[tid]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()},
             'task_completion_latency_ms':{tid:done[tid]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()},
             'task_completion_tardiness_ms':{tid:max(0,done[tid]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()},
             'task_deadline_met':{tid:tid in done and done[tid]<=t['completion_deadline_ms'] for tid,t in tasks.items()}}
    for k,v in metrics.items():assert result[k]==v,(k,result[k],v)
    responses=[]
    for pid,onset in onsets.items():
        assert pid in terminated
        q=requests.get(pid);end=terminated[pid]['timestamp_ms']
        responses.append({'proposal_id':pid,'invalidity_observed_ms':onset,
                          'stop_request_latency_ms':q['timestamp_ms']-onset if q else None,
                          'stop_confirmed':terminated[pid]['reason']=='action_stopped',
                          'quiescence_latency_ms':end-onset,'termination_reason':terminated[pid]['reason'],
                          'request_timely':q is not None and q['timestamp_ms']-onset<=e['response_contract']['request_tolerance_ms'],
                          'quiescence_timely':end-onset<=e['response_contract']['quiescence_tolerance_ms'],
                          'actual_invalid_running_exposure_ms':exposure.get(pid,0),
                          'reference_ack_window_exposure_ms':reference.get(pid,0),
                          'extra_exposure_beyond_tolerance_ms':excess.get(pid,0)})
    waiting=set(result['waiting_recovery_task_ids'])
    statuses={tid:'withdrawn' if tid in withdrawn else 'completed' if tid in done else 'pending_validity' if tid in waiting else 'unresolved' for tid in tasks}
    return {'status':'author_recount_not_acceptance','actual_event_stages':phases or [{'actual_stage':'no_event'}],
            'service_recount':metrics,'request_disposition':statuses,'valid_withdrawal_by_task':{tid:tid in expected_withdrawn for tid,c in contracts.items() if c['mode']=='withdraw'},
            'trusted_dependency_receipts_ms':done,
            'physical_completions_after_invalidation':physical_after_invalidation,
            'physical_completions_after_withdrawal':physical_after_withdrawal,'response_records':responses,
            'harm_duration_ms':harm,'zero_harm':harm==0,'execution_intervals':intervals,
            'attribution':'trusted local interlock; reference delay is synthetic, not empirical inevitability or LLM error'}
