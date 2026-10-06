import json,copy,hashlib,sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');B='homecoord_bench/task_revision/fixtures/c4_v9';sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from homecoord_bench.task_revision.c4_revision_v9 import PublicC4,bundle
from homecoord_bench.task_revision.event_simulator_v9 import run_event_simulation
main=read(R/B/'inputs.json')['episodes'];diag=read(R/B/'diagnostic_inputs.json')['cases'];eps={e['episode_id']:e for e in main+[x['episode'] for x in diag]};idx=read(R/B/'index.json')
class Capture(PublicC4):
    def __init__(self,*a):super().__init__(*a);self.instructions=[];self.hook_called=False
    def decide(self,q,instructions):self.instructions.append(instructions);return super().decide(q,instructions)
captures=[]
for file in idx['run_files']+idx['diagnostic_files']:
    for i,saved in enumerate(read(R/file)['runs']):
        c=Capture(saved['declared_proposal_latency_ms']);tr,res=run_event_simulation(eps[saved['evaluation_episode_id']],c,saved['policy'],'',shared_safety_gate=True)
        captures.append({'file':file,'run_index':i,'saved_trace_result_calls_equal':tr==saved['trace'] and res==saved['result'] and c.calls==saved['calls'],'instructions_empty':all(s=='' for s in c.instructions)})
canaries=[]
for e in eps.values():
    changed=copy.deepcopy(e);changed['episode_id']=changed['base_episode_id']='PRIVATE-MID-future';changed['nominal_window']='PRIVATE-window';changed['variant']={'private':'PRIVATE-condition'}
    for t in changed['task_stream']:t['goal']='PRIVATE-goal';t['action_template']['private']='PRIVATE-template'
    for tool in changed['tool_catalog']:tool['description']='PRIVATE-description'
    x=Capture();y=Capture();xt,_=run_event_simulation(e,x,'ConstraintCoordinator','',shared_safety_gate=True);yt,_=run_event_simulation(changed,y,'ConstraintCoordinator','',shared_safety_gate=True)
    canaries.append({'episode_id':e['episode_id'],'actual_inputs_equal':xt['agent_requests']==yt['agent_requests']})
negative=[]
class Hook(Capture):
    def prepare_release_batch(self,*a,**k):self.hook_called=True
base=main[0]
def reject(case,e,provider=None,policy='ConstraintCoordinator',instructions=''):
    c=provider or Capture()
    try:run_event_simulation(e,c,policy,instructions,shared_safety_gate=True);ok=False;msg=None
    except ValueError as x:ok=not c.calls and not c.hook_called;msg=str(x)
    negative.append({'case':case,'rejected_before_calls':ok,'message':msg})
reject('hook',base,Hook());reject('instructions',base,instructions='PRIVATE')
for pol in ('CentralSingleAgent','RobustReserveCoordinator','ObservedTaskFeasibilityCoordinator'):reject(pol,base,policy=pol)
for mut in ('tolerance','authority','external_receipt','batch_plan','nonboolean'):
    e=copy.deepcopy(base)
    if mut=='tolerance':e['response_contract']['quiescence_tolerance_ms']=700
    elif mut=='authority':e['user_lifecycle_policy']['principal']=''
    elif mut=='external_receipt':e['exogenous_events'][0]['patch']['service.work_completed']=True
    elif mut=='batch_plan':e['simulation']['released_batch_plan']={}
    else:e['initial_state']['values']['bedroom']['occupied']='false'
    reject(mut,e)
data=bundle();reproduction={p:read(R/p)==v for p,v in data.items()}
# Previous independently saved hashes and declared frozen manifests; no old model runs.
source=Path('work/probe_f2_v7.py').read_text(encoding='utf-8');exec(source[source.index('frozen=[]'):source.index('data=bundle()')])
for version in ('f2_v7','f3_v8'):
    mpath=R/'homecoord_bench/task_revision/fixtures'/version/'manifest.json';m=read(mpath)
    if version=='f3_v8':frozen.append({'file':str(mpath.relative_to(R)),'unchanged':sha(mpath)==read(O/'F3_V8_EVENT_AUDIT_20261002.json')['manifest_sha256'],'reference':'previous independent review'})
    for section in ('source_sha256','artifact_sha256'):
        for p,h in m[section].items():frozen.append({'file':p,'unchanged':sha(R/p)==h,'reference':version+' declared manifest'})
out={'captures':captures,'private_canaries':canaries,'negative_probes':negative,'bundle_reproduction':reproduction,'frozen_checks':frozen,'scoped_tests':{'module':'homecoord_bench.tests.test_c4_v9','tests':17,'failures':0,'errors':0,'does_not_test_clean_invalidated_natural_completion_semantics':True,'full466_not_run':True}}
(O/'C4_V9_RUNTIME_PROBES_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'capture96':all(c['saved_trace_result_calls_equal'] and c['instructions_empty'] for c in captures),'canary24':all(c['actual_inputs_equal'] for c in canaries),'negative':len(negative),'all_rejected':all(n['rejected_before_calls'] for n in negative),'reproduction_files':len(reproduction),'all_reproduced':all(reproduction.values()),'frozen_checks':len(frozen),'frozen_errors':[x for x in frozen if not x['unchanged']]},indent=2))
