"""Author-defined laundry DAG integration, offline only; print artifact chunks."""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.append(str(ROOT.parent))
from make_representative_revision_drafts import load_candidate, _tool
from homecoord_bench.task_revision.milestone import FixedProposals
from homecoord_bench.task_revision.event_simulator_v3 import run_event_simulation
from homecoord_bench.task_revision.dependency_audit import audit, metrics


class FailedWasher(FixedProposals):
    def decide(self, request, instructions=''):
        response = super().decide(request,instructions)
        if request['task']['task_id']=='wash':
            response['actions'][0]['operation']='unsupported'
        return response


def episode(condition):
    e = load_candidate('HC-M12')
    e['episode_id']='DEP-LAUNDRY-'+condition
    e['base_episode_id']='HC-M12'
    e['review_status']='author_revised_not_independently_reviewed'
    e['tool_contract_version']='strict-v1'
    e['task_family']='completion_dependency'
    e['simulation']={'command_latency_ms':100}
    e['home']['resources']['max_power_kw']=6
    e['conflict_rules']=[]
    e['initial_state']['values']['laundry']['wash_authorized']=True
    e['initial_state']['values']['service']={'wash_completed':False,'dry_completed':False}
    wash,dry = e['task_stream']
    wash['action_template']['requires']=[{'path':'laundry.wash_authorized','op':'eq','value':True}]
    dry['depends_on']=['wash']
    dry['release_at_ms']=5000 if condition=='LATE_REQUEST' else 100
    dry['action_template']['requires']=[{'path':'laundry.washed','op':'eq','value':True}]
    for t in (wash,dry): t['completion_deadline_ms']=15000
    if condition=='TIGHT_DEADLINE': dry['completion_deadline_ms']=8000
    for agent in e['agents']:
        agent['observable_state']=sorted(set(agent['observable_state']+['laundry.washed','laundry.wash_authorized']))
    e['tool_catalog']=[]
    for task in (wash,dry):
        t=task['action_template']
        ground=next(g for g in e['action_grounding'] if g['task_id']==task['task_id'])
        ground.pop('effects',None)
        ground['start_effects']={'devices.'+t['target']:'running'}
        ground['completion_effects']={'devices.'+t['target']:'off',
                                       'laundry.'+('washed' if task is wash else 'dry'):True,
                                       'service.'+task['task_id']+'_completed':True}
        agent=next(a for a in e['agents'] if a['agent_id']==task['agent_id'])
        e['tool_catalog'].append(_tool(agent['agent_id'],agent['tools'][0],task['goal'],t['target'],t['operation'],{},t['requires']))
    e['constraints']=[{'when':[{'path':'devices.dryer','op':'eq','value':'running'}],
                       'must':[{'path':'laundry.washed','op':'eq','value':True}]}]
    if condition in ('CANCEL_WASH','RESTART_WASH'):
        e['simulation']['lifecycle_contracts']={'wash':{
            'mode':'withdraw' if condition=='CANCEL_WASH' else 'restart_from_zero',
            'valid_when':deepcopy(wash['action_template']['requires']),
            'stop_ack_delay_ms':200,'restart_delay_ms':0,'stop_effects':{'devices.washer':'off'}}}
        e['exogenous_events']=[{'at_ms':1000,'event':'wash_authorization_revoked','patch':{'laundry.wash_authorized':False}}]
        if condition=='RESTART_WASH':
            e['exogenous_events'].append({'at_ms':5000,'event':'wash_authorization_restored','patch':{'laundry.wash_authorized':True}})
    if condition=='FORGED_STATE':
        e['exogenous_events']=[{'at_ms':450,'event':'untrusted_state_patch','patch':{'laundry.washed':True}}]
    if condition in ('CAPACITY_TIGHT','CAPACITY_SAFE'):
        capacity=3 if condition=='CAPACITY_TIGHT' else 6
        e['home']['resources']['max_power_kw']=capacity
        e['conflict_rules']=[{'type':'C3','capacity':capacity}]
        e['initial_state']['values']['devices']['dishwasher']='off'
        e['initial_state']['values']['service']['dishes_completed']=False
        e['agents'].append({'agent_id':'DishesAgent','role':'dishes','tools':['start_dishwasher'],
                           'observable_state':['devices.dishwasher'],'writable_resources':['devices.dishwasher']})
        t={'task_id':'dishes','agent_id':'DishesAgent','release_at_ms':0,'priority':60,
           'completion_deadline_ms':15000,'goal':'complete an independent dishes service',
           'required_action':{'target':'dishwasher','operation':'wash_dishes'},
           'action_template':{'target':'dishwasher','operation':'wash_dishes','parameters':{},
                              'requires':[],'duration_ms':8000,'power_kw':1.5}}
        e['task_stream'].append(t)
        e['tool_catalog'].append(_tool('DishesAgent','start_dishwasher',t['goal'],'dishwasher','wash_dishes',{}))
        e['action_grounding'].append({'agent_id':'DishesAgent','task_id':'dishes','target':'dishwasher','operation':'wash_dishes',
                                      'grounded_operation':'wash_dishes','duration_ms':8000,'power_kw':1.5,
                                      'start_effects':{'devices.dishwasher':'running'},
                                      'completion_effects':{'devices.dishwasher':'off','service.dishes_completed':True}})
    e['goals']=[{'path':'service.wash_completed','op':'eq','value':True},
                {'path':'service.dry_completed','op':'eq','value':True}]
    e['calibration']={'status':'abstract_author_service_contract','physical_parameters_verified':False}
    e['task_card']={'request_vs_execution':'Dry request can be released before wash completes; its valid conditional proposal waits.',
                    'dependency_receipt':'Only successful, non-withdrawn wash action_completed; state patches are insufficient.',
                    'sources':'HC-M12 problem structure; all times/powers synthetic, no physical laundry claim',
                    'review':'author-only; human independent review missing',
                    'condition':condition,'split':'development',
                    'controls':'EARLY/LATE change dry release only; CAPACITY_TIGHT/SAFE change capacity only',
                    'not_claimed':'LLM advantage, multi-agent necessity, or independent sample per policy'}
    return e


CONDITIONS=('EARLY_REQUEST','LATE_REQUEST','TIGHT_DEADLINE','CANCEL_WASH','RESTART_WASH','FORGED_STATE','FAILED_WASH','CAPACITY_TIGHT','CAPACITY_SAFE')
POLICIES=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')


def run(e, policy='ConstraintCoordinator', enabled=True):
    inp=deepcopy(e)
    if not enabled:
        for task in inp['task_stream']: task.pop('depends_on',None)
    provider=FailedWasher() if e['task_card']['condition']=='FAILED_WASH' else FixedProposals()
    trace,result=run_event_simulation(inp,provider,policy,'',shared_safety_gate=True)
    scored=metrics(e,trace,result)
    checked=audit(e,trace,scored,enforce_dependencies=enabled)
    return {'episode_id':e['episode_id'],'policy':policy,'dependencies_enabled':enabled,
            'metrics':scored,'audit':checked,
            'trace':{k:trace[k] for k in ('episode_id','policy','events','final_state','final_state_version')}}


def bundle():
    episodes=[episode(c) for c in CONDITIONS]
    runs=[run(e,p,on) for e in episodes for p in POLICIES for on in (False,True)]
    for r in runs:
        if not r['dependencies_enabled']: continue
        c=r['episode_id'].removeprefix('DEP-LAUNDRY-')
        assert r['metrics']['dry_started_without_wash_receipt']==0
        if c in ('CANCEL_WASH','FAILED_WASH'): assert not r['metrics']['completed']['dry']
        elif c!='CAPACITY_TIGHT' or r['policy']!='IndependentMultiAgent': assert r['metrics']['completed']['dry']
    data={'homecoord_bench/task_revision/fixtures/dependency_v3_inputs.json':{'status':'development_author_drafts','episodes':episodes},
          'homecoord_bench/results/dependency_v3_offline_20261001.json':{'api_calls':0,'heldout_content_read':0,
              'configurations':len(episodes),'policy_runs':len(runs),'matched_pairs':len(runs)//2,
              'status':'offline_abstract_dependency_integration_not_model_or_physical_evidence','runs':runs}}
    source_names=('dependency_pilot.py','dependency_contract.py','dependency_audit.py','event_simulator_v3.py')
    data['homecoord_bench/task_revision/fixtures/dependency_v3_manifest.json']={
        'status':'development_offline_snapshot',
        'source_sha256':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in source_names},
        'input_sha256':hashlib.sha256((json.dumps(data[next(iter(data))],ensure_ascii=False,indent=2)+'\n').encode()).hexdigest(),
        'migration':'explicit v3 entry; v1 and v2 sources/fixtures remain frozen','api_calls':0}
    return data


if __name__=='__main__':
    data=bundle()
    if len(sys.argv)==1: print(json.dumps({'artifacts':list(data),'configurations':9,'policy_runs':72,'matched_pairs':36}))
    else:
        value=json.dumps(data[sys.argv[1]],ensure_ascii=False,indent=2)+'\n'
        offset=int(sys.argv[2]) if len(sys.argv)>2 else 0
        print(json.dumps({'text':value[offset:offset+18000],
                          'next_offset':offset+18000 if len(value)>offset+18000 else None},ensure_ascii=True))
