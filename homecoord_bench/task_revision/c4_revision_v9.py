"""C4 v9 author revision: fixed world clocks, actual phase and terminal withdrawal."""
import hashlib,json
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.lifecycle_pilot import episode as old_episode
from homecoord_bench.task_revision.c4_contract_v9 import POLICIES
from homecoord_bench.task_revision.c4_audit_v9 import audit
from homecoord_bench.task_revision.event_simulator_v9 import run_event_simulation
from runtime.dry_run import _decision_from_template

ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'homecoord_bench';OUT='homecoord_bench/task_revision/fixtures/c4_v9'
WINDOWS={'NOEVENT':None,'EARLY':100,'MID':1800,'LATE':3000,'BOUNDARY':3400,'POST':4000,'UNRELATED':1800}


def episode(kind,window,ack=200):
    e=old_episode(kind,'NOEVENT',ack);e['episode_id']=f'C4R1-{kind}-{window}'
    e['c4_scene']=kind;e['c4_version']='stage-response-withdrawal-v1';e['nominal_window']=window
    e['review_status']='author_revision_design_and_implementation_pending'
    e['response_contract']={'detection_delay_ms':0,'request_tolerance_ms':0,'quiescence_tolerance_ms':200,'reference_ack_delay_ms':200}
    e['user_lifecycle_policy']={'principal':'SyntheticResident','authority':'explicit_synthetic_user_delegation',
                              'rule':'vacancy restores a cleaning request from zero; rain permanently cancels this irrigation request, even if it later stops',
                              'new_request_rule':'irrigation after rain ends requires a new task_id; terminal original never revives',
                              'parameter_basis':'synthetic Boolean policy and actuator delays, not measured household dynamics'}
    main=e['task_stream'][0];signal=main['action_template']['requires'][0]['path']
    at=WINDOWS[window];e['exogenous_events']=[]
    if at is not None:
        if window=='UNRELATED':e['exogenous_events'].append({'at_ms':at,'event':'challenge_unrelated','patch':{'diagnostic.heartbeat':1}})
        else:
            e['exogenous_events'] += [{'at_ms':at,'event':'validity_lost','patch':{signal:True}},
                                      {'at_ms':5000,'event':'validity_restored','patch':{signal:False}}]
    # Same observation endpoint; enough time after rain ends for a fresh full cycle.
    e['exogenous_events'].append({'at_ms':10000,'event':'observation_end','patch':{'diagnostic.heartbeat':2}})
    for tool in e['tool_catalog']:
        g=next(g for g in e['action_grounding'] if g['agent_id']==tool['agent_id'] and g['target']==tool['target'])
        tool['cost_contract']={'duration_ms':g['duration_ms'],'resource_units':g['power_kw']}
    return e


class PublicC4:
    include_evaluation_hints=False
    def __init__(self,latency=300):self.last_latency_ms=latency;self.calls=[]
    def decide(self,r,instructions):
        tool=r['available_actions'][0]
        t={'target':tool['target'],'operation':tool['operation'],'parameters':{},
           'requires':tool['preconditions'],'duration_ms':tool['cost_contract']['duration_ms'],
           'power_kw':tool['cost_contract']['resource_units']}
        d=_decision_from_template(r,t,r['state_version']);self.calls.append({'request':deepcopy(r),'decision':deepcopy(d)})
        return d


def run(e,policy='ConstraintCoordinator',latency=300):
    provider=PublicC4(latency)
    trace,result=run_event_simulation(e,provider,policy,'',shared_safety_gate=True)
    return {'evaluation_episode_id':e['episode_id'],'policy':policy,'declared_proposal_latency_ms':latency,
            'calls':provider.calls,'trace':trace,'result':result,'audit':audit(e,trace,result,provider.calls)}


def diagnostic_inputs():
    rows=[]
    for kind in ('CLEAN','RAIN'):
        for case in ('slow_proposal','slow_ack','late_natural_race','local_only'):
            e=episode(kind,'LATE' if case=='late_natural_race' else 'MID',1000 if case=='late_natural_race' else 700 if case=='slow_ack' else 200)
            latency=2500 if case=='slow_proposal' else 300
            if case=='local_only':
                e['c4_local_interlock_control']=True
                tid=e['task_stream'][1]['task_id'];aid=e['task_stream'][1]['agent_id']
                e['task_stream']=e['task_stream'][:1];e['agents']=[a for a in e['agents'] if a['agent_id']!=aid]
                e['tool_catalog']=[t for t in e['tool_catalog'] if t['agent_id']!=aid]
                e['action_grounding']=[g for g in e['action_grounding'] if g['task_id']!=tid]
                e['goals']=[g for g in e['goals'] if g['path']!='service.monitor_completed']
            e['episode_id']+='-'+case;rows.append({'case':case,'episode':e,'latency':latency})
    e=episode('CLEAN','MID');e['episode_id']+='-never_restore'
    e['exogenous_events']=[x for x in e['exogenous_events'] if x['event']!='validity_restored']
    rows.append({'case':'never_restore','episode':e,'latency':300})
    e=episode('RAIN','MID');e['episode_id']+='-new_request'
    t=deepcopy(e['task_stream'][0]);old=t['task_id'];t['task_id']=old+'_new';t['release_at_ms']=5500;e['task_stream'].append(t)
    g=deepcopy(next(g for g in e['action_grounding'] if g['task_id']==old));g['task_id']=t['task_id'];e['action_grounding'].append(g)
    e['simulation']['lifecycle_contracts'][t['task_id']]=deepcopy(e['simulation']['lifecycle_contracts'][old])
    rows.append({'case':'new_request','episode':e,'latency':300})
    return rows


def serialize(v):return json.dumps(v,ensure_ascii=False,indent=2)+'\n'


def bundle():
    episodes=[episode(k,w) for k in ('CLEAN','RAIN') for w in WINDOWS]
    diagnostics=diagnostic_inputs()
    data={OUT+'/inputs.json':{'episodes':episodes,'acceptance':None},OUT+'/diagnostic_inputs.json':{'cases':diagnostics}}
    by_key={};files=[];diag_files=[];controls=[]
    for e in episodes:
        rows=[run(e,p) for p in POLICIES];by_key[(e['c4_scene'],e['nominal_window'])]=rows
        name=OUT+'/runs/'+e['episode_id']+'.json';files.append(name);data[name]={'runs':rows}
    for x in diagnostics:
        e=x['episode'];rows=[run(e,p,x['latency']) for p in POLICIES]
        name=OUT+'/diagnostics/'+e['episode_id']+'.json';diag_files.append(name);data[name]={'case':x['case'],'runs':rows}
        if x['case']=='local_only':
            for a,b in zip(rows,by_key[(e['c4_scene'],'MID')]):
                tid=e['task_stream'][0]['task_id']
                assert a['audit']['harm_duration_ms']==b['audit']['harm_duration_ms']
                for k in a['audit']['service_recount']:assert a['audit']['service_recount'][k][tid]==b['audit']['service_recount'][k][tid]
                # Proposal identities and stop response timings match the local interlock.
                assert a['audit']['response_records']==b['audit']['response_records']
                controls.append({'scene':e['c4_scene'],'policy':a['policy'],'main_service_and_response_equal':True,
                                 'scope':'second agent has no established gain; same local information and stopping capability'})
    data[OUT+'/index.json']={'main_configurations':14,'main_runs':56,'diagnostic_configurations':10,'diagnostic_runs':40,
                           'api_calls':0,'holdout_runs':0,'run_files':files,'diagnostic_files':diag_files,
                           'local_interlock_controls':controls,'acceptance':None}
    paths=['homecoord_bench/task_revision/'+n for n in ('c4_contract_v9.py','c4_audit_v9.py','c4_revision_v9.py','event_simulator_v9.py','c4_lifecycle_contract_v9.py',
                                                       'lifecycle_pilot.py','lifecycle_contract.py','lifecycle_audit.py','event_simulator_v2.py','milestone.py')]
    paths+=['homecoord_bench/runtime/'+n for n in ('protocol.py','execution.py','episode_validation.py','tool_contract.py','task_response_metrics.py','dry_run.py')]
    paths+=['homecoord_bench/task_revision/c4_evaluate_v9.py','homecoord_bench/evaluate.py','homecoord_bench/tests/test_c4_v9.py']
    data[OUT+'/manifest.json']={'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
                              'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},
                              'acceptance':None,'prior_versions':'v1-v8 and frozen data/Phase A/B unchanged'}
    return data


if __name__=='__main__':
    import sys
    data=bundle();print(json.dumps(list(data) if len(sys.argv)==1 else serialize(data[sys.argv[1]]),ensure_ascii=True))
