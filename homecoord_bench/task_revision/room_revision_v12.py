"""C2 v12 demand-aware rules; full traces are losslessly encoded, no API."""
import json,hashlib,zlib,base64
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.room_pilot import episode as previous_episode,run as previous_run
from homecoord_bench.task_revision.c4_revision_v9 import PublicC4,serialize
from homecoord_bench.task_revision.event_simulator_v12 import run_event_simulation
from homecoord_bench.task_revision.room_contract_v12 import AUTHORITY
from homecoord_bench.task_revision.room_audit_v12 import audit
ROOT=Path(__file__).resolve().parents[2];OUT='homecoord_bench/task_revision/fixtures/room_v12'

def episode(co2=1600,vent=2.5,heat=.025,admission='immediate'):
    e=previous_episode(co2,vent,heat,admission);e['episode_id']='C2R12-'+e['episode_id']
    e['c2_revision']='v12-demand-disposition';e['controller_authority']=deepcopy(AUTHORITY)
    e['review_status']='author_revision_pending'
    for task in e['task_stream']:
        task['completion_deadline_ms']=e['simulation']['environment']['deadline_ms']
        task['goal']='Issue the authorized heating command; environmental temperature service is scored separately.'
        if task['task_id']=='bedroom_air':
            task['goal']='Ensure requested air quality: if currently satisfied, keep window closed without an opening command; otherwise ventilate and use trusted closure.'
            task['demand_rule']={'path':'bedroom.co2_ppm','threshold_ppm':900,'satisfied_action':'keep_window_closed','unsatisfied_action':'ventilate_then_trusted_close'}
            task['action_template']['requires']=[{'path':'bedroom.co2_ppm','op':'gt','value':900}]
    for tool in e['tool_catalog']:
        g=next(g for g in e['action_grounding'] if g['agent_id']==tool['agent_id'])
        tool['cost_contract']={'duration_ms':g['duration_ms'],'resource_units':0}
        if tool['target']=='window':tool['preconditions']=[{'path':'bedroom.co2_ppm','op':'gt','value':900}]
    e['task_card']={'scope':'single uncalibrated room, demand disposition separate from command and environmental success',
        'review':None,'comparison':'only trusted heat_admission rule differs within each parameter world'}
    return e

class Provider(PublicC4):
    def __init__(self,mode='conditional'):super().__init__(300);self.mode=mode
    def decide(self,r,instructions):
        air=r['task']['task_id']=='bedroom_air'
        skip=air and (self.mode=='always_skip' or self.mode=='conditional' and r['state']['bedroom']['co2_ppm']<=r['task']['demand_rule']['threshold_ppm'])
        if skip:
            d={'response_type':'defer','actions':[],'accepted_proposal_ids':[],'rejected_proposal_ids':[],
               'defer_until_ms':None,'reason_code':'no_applicable_action'}
            self.calls.append({'request':deepcopy(r),'decision':deepcopy(d)});return d
        return super().decide(r,instructions)

def run(e,mode='conditional'):
    provider=Provider(mode)
    trace,result=run_event_simulation(e,provider,'ConstraintCoordinator','',shared_safety_gate=True)
    return {'trace':trace,'result':result,'calls':provider.calls,'audit':audit(e,trace,result,provider.calls)}

def pack(row):
    trace=row['trace'];text=json.dumps(trace,ensure_ascii=False,separators=(',',':'))
    return {k:v for k,v in row.items() if k!='trace'}|{'trace_encoding':'zlib+base64+utf8-json',
        'trace_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'trace_zlib_base64':base64.b64encode(zlib.compress(text.encode(),9)).decode(),
        'readable_non_environment_events':[x for x in trace['events'] if not(x['type']=='state_update' and x.get('source')=='synthetic_environment')]}

def unpack(row):
    raw=zlib.decompress(base64.b64decode(row['trace_zlib_base64']))
    assert hashlib.sha256(raw).hexdigest()==row['trace_sha256']
    return {k:row[k] for k in ('result','calls','audit')}|{'trace':json.loads(raw)}

def bundle():
    episodes=[episode(c,v,h,a) for c in (1600,850) for v in (2.5,5.) for h in (.015,.025,.035) for a in ('immediate','after_ventilation')]
    diagnostics=[{'case':name,'episode':episode(c,admission=a),'mode':mode}
        for name,c,mode in (('unnecessary_open',850,'always_open'),('unhandled_high_co2',1600,'always_skip'),('exact_threshold',900,'conditional'),('above_threshold',901,'conditional'))
        for a in ('immediate','after_ventilation')]
    data={OUT+'/inputs.json':{'episodes':episodes,'diagnostics':diagnostics,'acceptance':None}};compat=[]
    for e in episodes:
        row=run(e);p=e['simulation']['environment'];c=e['initial_state']['values']['bedroom']['co2_ppm']
        old=previous_run(previous_episode(c,p['ventilation_rate_ppm_s'],p['heat_rate_c_per_s'],p['heat_admission']))
        assert row['result']['environment']==old['environment']
        path=OUT+'/runs/'+e['episode_id']+'.json';data[path]=pack(row)
        compat.append({'episode_id':e['episode_id'],'frozen_v4_environment_equal':True})
    for x in diagnostics:data[OUT+'/diagnostics/'+x['case']+'-'+x['episode']['simulation']['environment']['heat_admission']+'.json']=pack(run(x['episode'],x['mode']))
    data[OUT+'/index.json']={'main_runs':24,'parameter_worlds':12,'diagnostic_runs':8,'policy':'ConstraintCoordinator',
        'comparison':'two trusted heating-admission rules, not LLM methods','v4_physics_compatibility':compat,'api_calls':0,'holdout_runs':0,'acceptance':None}
    paths=['homecoord_bench/task_revision/'+n for n in ('event_simulator_v12.py','room_contract_v12.py','room_audit_v12.py','room_revision_v12.py','event_simulator_v4.py','room_environment.py','room_pilot.py','room_audit.py')]
    paths+=['homecoord_bench/tests/test_room_v12.py']
    data[OUT+'/manifest.json']={'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},'acceptance':None}
    return data
if __name__=='__main__':
    import sys
    b=bundle();print(json.dumps(list(b) if len(sys.argv)==1 else serialize(b[sys.argv[1]]),ensure_ascii=True))
