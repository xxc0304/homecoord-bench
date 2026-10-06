import json,copy,sys,hashlib
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from homecoord_bench.task_revision.f2_revision import inputs,run,PublicProposals,bundle
from homecoord_bench.task_revision.f2_information import POLICIES
from homecoord_bench.task_revision.event_simulator_v7 import run_event_simulation
eps=inputs();probes=[]
class Capture(PublicProposals):
    def __init__(self):super().__init__();self.instructions=[];self.hook_called=False
    def decide(self,q,instructions):self.instructions.append(instructions);return super().decide(q,instructions)
with patch('homecoord_bench.task_revision.event_simulator_v7.ideal_schedule',side_effect=AssertionError('online oracle forbidden')):
    for e in eps:
        saved=read(R/'homecoord_bench/task_revision/fixtures/f2_v7/runs'/f"{e['episode_id']}.json")
        for i,p in enumerate(POLICIES):
            c=Capture();a=run(e,p,c)
            probes.append({'episode_id':e['episode_id'],'policy':p,'saved_run_equal':a==saved['runs'][i],'provider_trace_equal':[x['request'] for x in c.calls]==a['trace']['agent_requests'],'instructions_empty':all(x=='' for x in c.instructions),'oracle_not_called':True})
class Hook(Capture):
    def prepare_release_batch(self,*a,**kw):self.hook_called=True
negative=[]
def reject(name,e,policy='ConstraintCoordinator',instructions='',provider=None,**kw):
    c=provider or Capture()
    try:run_event_simulation(e,c,policy,instructions,shared_safety_gate=True,**kw);ok=False;error=None
    except ValueError as x:ok=not c.calls and not c.hook_called;error=str(x)
    negative.append({'case':name,'rejected_before_calls':ok,'error':error})
base=eps[0]
reject('episode_hook',base,provider=Hook());reject('external_instructions',base,instructions='private future request')
for p in ('CentralSingleAgent','RobustReserveCoordinator','ObservedTaskFeasibilityCoordinator','CapacityAwareDeadlineCoordinator','FixedHoldCoordinator'):reject(p,base,policy=p)
for name in ('future_reserve','batch_plan','compute_plan','constraints','static_metadata','cost_mismatch','missing_delegation'):
    e=copy.deepcopy(base)
    if name=='future_reserve':e['simulation']['potential_urgent']={'task_id':'water'}
    elif name=='batch_plan':e['simulation']['released_batch_plan']={}
    elif name=='compute_plan':e['simulation']['coordination_compute_profile']={}
    elif name=='constraints':e['constraints']=[{'hidden':'private'}]
    elif name=='static_metadata':e['public_devices'][0]['private']='future'
    elif name=='cost_mismatch':e['public_devices'][0]['duration_ms']+=1
    else:e['nonpreemptive_delegation']={}
    reject(name,e)
reject('synthetic_id_based_latency',base,synthetic_latency=True);reject('external_coordination_delay',base,coordination_delay_ms=100)
class NoAction(Capture):
    def decide(self,q,instructions):
        self.instructions.append(instructions);d={'response_type':'noop','actions':[],'accepted_proposal_ids':[],'rejected_proposal_ids':[],'defer_until_ms':None,'reason_code':'no_applicable_action'};self.calls.append({'request':copy.deepcopy(q),'decision':d});return d
noaction=[]
for p in POLICIES:
    a=run(base,p,NoAction());res=a['result']
    noaction.append({'policy':p,'all_false_null':all(v is False for v in res['task_correct_action_completed'].values()) and all(v is None for v in res['task_completion_latency_ms'].values()) and all(v is False for v in res['task_deadline_met'].values()),'run':a})
frozen=[]
prior=read(O/'PHASE_B_EVENT_AUDIT.json')['summary'];mp=R/'docs/implementation_review_20261001/manifest.json'
frozen.append({'file':str(mp.relative_to(R)),'unchanged':sha(mp)==prior['manifest_sha256']})
m=read(mp)
for section in ('source_sha256','artifact_sha256','historical_result_sha256'):
    for path,h in m[section].items():frozen.append({'file':path,'unchanged':sha(R/path)==h})
for version,hashes in {
 'v5':{'homecoord_bench/task_revision/fixtures/protection_v5_inputs.json':'dfc7b9ca310cbcc993a33af4aa2720ec3e63ff6b07ab18847730f92c3dc5bfd3','homecoord_bench/results/protection_v5_offline_20261002.json':'361aa9078cf0344399271c60826f0d864058ca82258658ed2f7bc053566f8d0c'},
 'v6':{'homecoord_bench/task_revision/fixtures/protection_v6_inputs.json':'48bcf2e199533bc655b78ec54abee94a15e0b314c70b20e2bddafd4dfba7c9fb','homecoord_bench/results/protection_v6_offline_20261002.json':'448d8f4b0c19996f90c2d3cb27afe0d0fb14de2b4d278f95a5fe4b71787907d9'}}.items():
    for path,h in hashes.items():frozen.append({'file':path,'unchanged':sha(R/path)==h})
data=bundle();repro={p:read(R/p)==v for p,v in data.items()}
o={'actual_capture_probes':probes,'negative_probes':negative,'no_action_diagnostics':noaction,'frozen_hash_checks':frozen,'bundle_reproduction':repro,'scoped_author_tests':{'module':'homecoord_bench.tests.test_f2_v7','tests_run':13,'failures':0,'errors':0,'exit_code':0,'full433_suite_not_run':True}}
(O/'F2_V7_RUNTIME_PROBES_20261002.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'capture32':all(x['saved_run_equal'] and x['provider_trace_equal'] and x['instructions_empty'] for x in probes),'negative':len(negative),'all_rejected':all(x['rejected_before_calls'] for x in negative),'noaction4':all(x['all_false_null'] for x in noaction),'frozen':len(frozen),'frozen_errors':[x for x in frozen if not x['unchanged']],'repro24':all(repro.values())},indent=2))
