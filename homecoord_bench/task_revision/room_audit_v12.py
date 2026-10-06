"""Independent C2 disposition/attempt replay plus frozen independent physics audit."""
from copy import deepcopy
from evaluate import get_path,set_path
from homecoord_bench.task_revision.room_audit import audit as physical_audit

def audit(e,trace,result,calls):
    physical=physical_audit(e,trace,result['environment'])
    assert trace['agent_requests']==[x['request'] for x in calls]
    for x in calls:
        r=x['request'];assert r['episode_id']=='HC-M06'
        assert not {'action_template','required_action','acceptable_actions'}&set(r['task'])
    tasks={t['task_id']:t for t in e['task_stream']};state=deepcopy(e['initial_state']['values'])
    active={};done={};skips={};admitted=set();version=e['initial_state']['version']
    for x in trace['events']:
        kind=x['type'];tid=x.get('task_id');now=x['timestamp_ms']
        if kind=='action_started':
            g=next(g for g in e['action_grounding'] if g['task_id']==tid)
            assert now>=tasks[tid]['release_at_ms']
            assert (x['target'],x['operation'],x['duration_ms'])==(g['target'],g['operation'],g['duration_ms'])
            if tid=='bedroom_air':assert get_path(state,'bedroom.co2_ppm')>900
            if tid=='bedroom_heat' and e['simulation']['environment']['heat_admission']=='after_ventilation':
                assert get_path(state,'devices.window')=='closed' and get_path(state,'bedroom.co2_ppm')<=900
            active[x['proposal_id']]=x
        if kind=='action_completed':
            s=active.pop(x['proposal_id']);assert s['task_id']==tid and now==s['timestamp_ms']+s['duration_ms']
            assert (s['target'],s['operation'])==(x['target'],x['operation']);done[tid]=now
        if kind=='request_satisfied_without_actuation':
            assert tid=='bedroom_air' and get_path(state,'bedroom.co2_ppm')<=900 and get_path(state,'devices.window')=='closed'
            assert not any(s['task_id']==tid for s in active.values())
            call=next(c for c in calls if c['request']['task']['task_id']==tid)
            assert call['decision']['response_type'] in ('defer','noop') and not call['decision']['actions']
            assert call['decision'].get('defer_until_ms') is None
            skips[tid]=now
        if kind in ('action_reserved','environment_admission_waiting','request_satisfied_without_actuation'):admitted.add(tid)
        if kind=='action_rejected' and x['reason']=='ventilation_not_needed':
            assert tid=='bedroom_air' and get_path(state,'bedroom.co2_ppm')<=900
        if kind in ('state_update','action_completed'):
            version+=1;assert x['new_state_version']==version
            for p,v in (x['patch'] if kind=='state_update' else x['effects']).items():set_path(state,p,v)
    assert not active and state==trace['final_state'] and version==trace['final_state_version']
    handled={**done,**skips}
    expected={'task_admission_legal':{tid:tid in admitted for tid in tasks},
        'task_correct_disposition':{tid:tid in handled for tid in tasks},
        'task_disposition':{tid:'satisfied_without_actuation' if tid in skips else 'command_completed' if tid in done else 'unresolved' for tid in tasks},
        'task_disposition_latency_ms':{tid:handled[tid]-t['release_at_ms'] if tid in handled else None for tid,t in tasks.items()},
        'task_disposition_deadline_met':{tid:tid in handled and handled[tid]<=t['completion_deadline_ms'] for tid,t in tasks.items()}}
    for k,v in expected.items():assert result[k]==v,(k,result[k],v)
    assert result['task_correct_action_completed']=={tid:tid in done for tid in tasks}
    assert result['task_completion_latency_ms']=={tid:done[tid]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()}
    return {'status':'author_recount_not_acceptance','request_recount':expected,'physical_recount':physical,
            'skipped_without_command':list(skips),'first_environment_goal_not_sustained_goal':True}
