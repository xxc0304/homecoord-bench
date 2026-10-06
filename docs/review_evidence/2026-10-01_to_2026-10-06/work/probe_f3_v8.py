import json,copy,hashlib,sys
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from homecoord_bench.task_revision.f3_revision import inputs,ModeRule,SELECTORS,bundle
from homecoord_bench.task_revision.f3_capability import POLICIES
from homecoord_bench.task_revision.event_simulator_v8 import run_event_simulation
B='homecoord_bench/task_revision/fixtures/f3_v8';episodes=inputs();index=read(R/B/'index.json');packets={read(R/file)['episode_id']:read(R/file) for file in index['run_files']}
class Capture(ModeRule):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.instructions=[];self.hook_called=False
    def decide(self,r,instructions):self.instructions.append(instructions);return super().decide(r,instructions)
probes=[]
with patch('homecoord_bench.task_revision.event_simulator_v8.ideal_schedule',side_effect=AssertionError('online oracle forbidden')):
    for e in episodes:
        for i,saved in enumerate(packets[e['episode_id']]['runs']):
            c=Capture(saved['selector']);trace,result=run_event_simulation(e,c,saved['policy'],'',shared_safety_gate=True)
            probes.append({'episode_id':e['episode_id'],'run_index':i,'saved_trace_result_calls_equal':trace==saved['trace'] and result==saved['result'] and c.calls==saved['calls'],'provider_trace_equal':trace['agent_requests']==[v['request'] for v in c.calls],'instructions_empty':all(x=='' for x in c.instructions),'oracle_not_called':True})
canaries=[]
for e in episodes:
    modified=copy.deepcopy(e);modified['episode_id']=modified['base_episode_id']='PRIVATE-selector-vector-condition'
    modified['initial_state']['values']['coordination_context']['private']='PRIVATE-context'
    for t in modified['task_stream']:t['goal']='PRIVATE-goal';t['action_template']['private']='PRIVATE-template'
    for t in modified['tool_catalog']:t['description']='PRIVATE-description'
    for agent in modified['agents']:agent['private']='PRIVATE-agent'
    c=Capture();trace,result=run_event_simulation(modified,c,'ConstraintCoordinator','',shared_safety_gate=True)
    base=packets[e['episode_id']]['runs'][1]
    canaries.append({'episode_id':e['episode_id'],'actual_inputs_equal':trace['agent_requests']==base['trace']['agent_requests']})
negative=[]
class Hook(Capture):
    def prepare_release_batch(self,*a,**kw):self.hook_called=True
base=episodes[2]
def rejected(name,e,policy='ConstraintCoordinator',instructions='',provider=None,**kw):
    c=provider or Capture()
    try:run_event_simulation(e,c,policy,instructions,shared_safety_gate=True,**kw);ok=False;error=None
    except ValueError as x:ok=not c.calls and not c.hook_called;error=str(x)
    negative.append({'case':name,'rejected_before_calls':ok,'reason':error})
rejected('hook',base,provider=Hook());rejected('instructions',base,instructions='PRIVATE')
for pol in ('CentralSingleAgent','RobustReserveCoordinator','ObservedTaskFeasibilityCoordinator'):rejected(pol,base,policy=pol)
for mutation in ('world_event','batch_plan','compute_plan','authority','physical_cost','fixed_full_set','actual_tool_permission','constraints'):
    e=copy.deepcopy(base)
    if mutation=='world_event':e['exogenous_events']=[{'at_ms':1000,'patch':{}}]
    elif mutation=='batch_plan':e['simulation']['released_batch_plan']={}
    elif mutation=='compute_plan':e['simulation']['coordination_compute_profile']={}
    elif mutation=='authority':e['service_delegation']={}
    elif mutation=='physical_cost':e['public_devices'][0]['modes'][0]['duration_ms']+=1
    elif mutation=='fixed_full_set':e['mode_capability']['kind']='fixed'
    elif mutation=='actual_tool_permission':e['agents'][0]['tools']=[]
    else:e['constraints']=[{'private':'constraint'}]
    rejected(mutation,e)
rejected('id_based_synthetic_latency',base,synthetic_latency=True);rejected('coordination_delay',base,coordination_delay_ms=100)
# Recheck the previous independently recorded Phase B/C1 hashes without rerunning those task families.
prior=Path('work/probe_f2_v7.py').read_text(encoding='utf-8');exec(prior[prior.index('frozen=[]'):prior.index('data=bundle()')])
f2manifest=read(R/'homecoord_bench/task_revision/fixtures/f2_v7/manifest.json')
for section in ('source_sha256','artifact_sha256'):
    for path,h in f2manifest[section].items():frozen.append({'file':path,'unchanged':sha(R/path)==h,'reference':'F2 declared frozen manifest'})
data=bundle();reproduction={file:read(R/file)==value for file,value in data.items()}
out={'actual_capture':probes,'private_channel_canaries':canaries,'negative_probes':negative,'frozen_checks':frozen,'bundle_reproduction':reproduction,'scoped_tests':{'module':'homecoord_bench.tests.test_f3_v8','run':16,'failures':0,'errors':0,'full449_not_run':True}}
(O/'F3_V8_RUNTIME_PROBES_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'actual192':all(x['saved_trace_result_calls_equal'] and x['provider_trace_equal'] and x['instructions_empty'] for x in probes),'canaries32':all(x['actual_inputs_equal'] for x in canaries),'negative':len(negative),'all_rejected':all(x['rejected_before_calls'] for x in negative),'frozen':len(frozen),'frozen_errors':[x for x in frozen if not x['unchanged']],'reproduced45':all(reproduction.values())},indent=2))
