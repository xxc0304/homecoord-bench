"""Dependency revision v11, abstract development contracts only."""
import json,hashlib
from pathlib import Path
from copy import deepcopy
from homecoord_bench.task_revision.dependency_pilot import episode as previous_episode
from homecoord_bench.task_revision.c4_revision_v9 import PublicC4,serialize
from homecoord_bench.task_revision.dependency_contract_v11 import POLICIES
from homecoord_bench.task_revision.event_simulator_v11 import run_event_simulation
from homecoord_bench.task_revision.dependency_audit_v11 import audit
ROOT=Path(__file__).resolve().parents[2];OUT='homecoord_bench/task_revision/fixtures/dependency_v11'
CONDITIONS=('EARLY','LATE','INFEASIBLE_8000','FEASIBLE_8500','CANCEL_NO_RESTORE','CANCEL_RESTORE','RESTART_NO_RESTORE','RESTART_RESTORE','INVALID_PROPOSAL','FORGED_STATE','STALE_NATURAL_RACE','CAPACITY_TIGHT','CAPACITY_SAFE')

def episode(c):
    old='LATE_REQUEST' if c=='LATE' else c if c in ('FORGED_STATE','CAPACITY_TIGHT','CAPACITY_SAFE') else 'EARLY_REQUEST'
    e=previous_episode(old);e['episode_id']='DEP11-'+c;e['dependency_revision']='v11-single-batch'
    e['batch_binding']={'wash':'batch_1','dry':'batch_1'};e['nominal_window']=c;e['review_status']='author_revision_pending'
    e['response_contract']={'detection_delay_ms':0,'request_tolerance_ms':0,'quiescence_tolerance_ms':200,'reference_ack_delay_ms':200}
    e['simulation']['lifecycle_contracts']={'wash':{'mode':'withdraw' if c.startswith('CANCEL') else 'restart_from_zero',
        'valid_when':[{'path':'laundry.wash_authorized','op':'eq','value':True}],
        'stop_ack_delay_ms':1000 if c=='STALE_NATURAL_RACE' else 200,'restart_delay_ms':0,'stop_effects':{'devices.washer':'off'}}}
    if c.startswith(('CANCEL','RESTART')) or c=='STALE_NATURAL_RACE':
        e['exogenous_events']=[{'at_ms':4000 if c=='STALE_NATURAL_RACE' else 1000,'event':'wash_authorization_revoked','patch':{'laundry.wash_authorized':False}}]
        if c.endswith('_RESTORE') and not c.endswith('_NO_RESTORE') or c=='STALE_NATURAL_RACE':
            e['exogenous_events'].append({'at_ms':5000,'event':'wash_authorization_restored','patch':{'laundry.wash_authorized':True}})
    if c in ('INFEASIBLE_8000','FEASIBLE_8500'):
        e['task_stream'][1]['completion_deadline_ms']=8000 if c=='INFEASIBLE_8000' else 8500
    e['evaluation_class']='infeasible_pressure' if c=='INFEASIBLE_8000' else 'invalid_proposal_diagnostic' if c=='INVALID_PROPOSAL' else 'synthetic_contract'
    e['authority']={'principal':'SyntheticResident','basis':'explicit synthetic laundry authorization; same single batch, no physical calibration'}
    e['exogenous_events'].append({'at_ms':16000,'event':'observation_end','patch':{'diagnostic.heartbeat':1}})
    e['initial_state']['values']['diagnostic']={'heartbeat':0}
    for t in e['tool_catalog']:
        g=next(g for g in e['action_grounding'] if g['agent_id']==t['agent_id'] and g['target']==t['target'])
        t['cost_contract']={'duration_ms':g['duration_ms'],'resource_units':g['power_kw']}
    e['task_card']={'contract':'trusted valid wash attempt gates dry in same single declared batch',
        'source':'v3 abstract parameters retained; 8500 deadline new','independent_review':None}
    return e

class Provider(PublicC4):
    def __init__(self,inject=False):super().__init__(300);self.inject=inject
    def decide(self,r,instructions):
        d=super().decide(r,instructions)
        if self.inject and r['task']['task_id']=='wash':
            d['actions'][0]['operation']='unsupported'
            self.calls[-1]['decision']=deepcopy(d)
        return d

def run(e,p='ConstraintCoordinator'):
    v=Provider(e['evaluation_class']=='invalid_proposal_diagnostic')
    trace,result=run_event_simulation(e,v,p,'',shared_safety_gate=True)
    return {'policy':p,'trace':trace,'result':result,'calls':v.calls,'audit':audit(e,trace,result,v.calls)}

def certificates():
    cert={}
    for c in CONDITIONS:
        if c.startswith('CANCEL') or c in ('RESTART_NO_RESTORE','INVALID_PROPOSAL'):
            cert[c]={'kind':'lifecycle_or_failure_diagnostic','all_service_expectation':False};continue
        if c=='INFEASIBLE_8000':
            cert[c]={'kind':'infeasible_under_frozen_300ms_proposal_100ms_command','earliest_wash_end_ms':4400,
                     'earliest_dry_end_ms':8500,'dry_deadline_ms':8000,'excluded_from_feasible_success_denominator':True};continue
        schedule=[{'task_id':'wash','start_ms':5100 if c in ('RESTART_RESTORE','STALE_NATURAL_RACE') else 400,'end_ms':9100 if c in ('RESTART_RESTORE','STALE_NATURAL_RACE') else 4400}]
        dry_start=9200 if c in ('RESTART_RESTORE','STALE_NATURAL_RACE') else 5400 if c=='LATE' else 8500 if c=='CAPACITY_TIGHT' else 4500
        schedule.append({'task_id':'dry','start_ms':dry_start,'end_ms':dry_start+4000})
        if c.startswith('CAPACITY'):schedule.append({'task_id':'dishes','start_ms':400,'end_ms':8400})
        e=episode(c);tasks={t['task_id']:t for t in e['task_stream']}
        for a in schedule:
            assert a['start_ms']>=tasks[a['task_id']]['release_at_ms']+400
            assert a['end_ms']-a['start_ms']==tasks[a['task_id']]['action_template']['duration_ms']
            assert a['end_ms']<=tasks[a['task_id']]['completion_deadline_ms']
        for at in sorted({a[k] for a in schedule for k in ('start_ms','end_ms')}):
            assert sum(tasks[a['task_id']]['action_template']['power_kw'] for a in schedule if a['start_ms']<=at<a['end_ms'])<=e['home']['resources']['max_power_kw']
        assert schedule[1]['start_ms']>=schedule[0]['end_ms']+100
        cert[c]={'kind':'constructive_feasible_under_frozen_overheads','schedule':schedule,'offline_reference_not_online_guarantee':True}
    return cert

def bundle():
    data={OUT+'/inputs.json':{'episodes':[episode(c) for c in CONDITIONS],'acceptance':None},
          OUT+'/certificates.json':certificates()}
    pairs=[]
    for mode in ('CANCEL','RESTART'):
        a,b=episode(mode+'_NO_RESTORE'),episode(mode+'_RESTORE')
        # IDs and nominal labels are private bookkeeping; only world recovery changes.
        for x in (a,b):x.pop('episode_id');x.pop('nominal_window')
        extra=[x for x in b['exogenous_events'] if x['event']=='wash_authorization_restored']
        b['exogenous_events']=[x for x in b['exogenous_events'] if x['event']!='wash_authorization_restored']
        assert a==b;pairs.append({'mode':mode,'only_world_difference':extra})
    for c in CONDITIONS:data[OUT+'/runs/'+c+'.json']={'runs':[run(episode(c),p) for p in POLICIES]}
    data[OUT+'/index.json']={'configurations':13,'runs':52,'recovery_single_factor_pairs':pairs,
                           'failure_injection':{'target_task':'wash','field':'actions[0].operation','normal':'wash','injected':'unsupported','proposal_return_ms':300,'expected_rejection':'tool_not_authorized','dry_status':'waiting without valid receipt, not terminal execution failure','retry_model_calls':0},
                           'api_calls':0,'holdout_runs':0,'acceptance':None}
    paths=['homecoord_bench/task_revision/'+n for n in ('event_simulator_v11.py','dependency_contract_v11.py','dependency_audit_v11.py','dependency_revision_v11.py')]
    paths+=['homecoord_bench/tests/test_dependency_v11.py']
    paths+=['homecoord_bench/task_revision/'+n for n in ('event_simulator_v3.py','dependency_pilot.py','dependency_contract.py','dependency_audit.py','lifecycle_contract.py')]
    paths+=['homecoord_bench/runtime/'+n for n in ('protocol.py','execution.py','tool_contract.py','task_response_metrics.py')]
    data[OUT+'/manifest.json']={'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},'acceptance':None}
    return data
if __name__=='__main__':
    import sys
    b=bundle();print(json.dumps(list(b) if len(sys.argv)==1 else serialize(b[sys.argv[1]]),ensure_ascii=True))
