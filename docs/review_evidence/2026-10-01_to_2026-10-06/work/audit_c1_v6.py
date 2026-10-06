import json,hashlib,copy,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(r'.');OUT=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
# Reuse the independent state/event/metric replay, adapting only v6 identities and separate admission.
src=Path('work/audit_c1_v5.py').read_text(encoding='utf-8')
src=src.replace('protection_v5_inputs.json','protection_v6_inputs.json').replace('protection_v5_manifest.json','protection_v6_manifest.json').replace('protection_v5_offline_20261002.json','protection_v6_offline_20261002.json')
src=src.replace("enumerate(packet['runs'])","enumerate(packet['runs']+packet['diagnostics'])")
src=src.replace("episodes[run['episode_id']]","episodes[run['evaluation_episode_id']]")
src=src[:src.index("out={'manifest_sha256'")]
exec(src)
old=read(ROOT/'homecoord_bench/results/protection_v5_offline_20261002.json')
core=['request_status','task_correct_action_completed','task_completion_latency_ms','task_deadline_met','state_constraint_violation_duration_ms']
for i,r in enumerate(packet['runs']+packet['diagnostics']):
    d=details[i];e=episodes[r['evaluation_episode_id']];low=e['task_stream'][1]['task_id'];ev=r['trace']['events'];a=r['audit']
    ae=[(j,x) for j,x in enumerate(ev) if x['type'] in ('request_admitted','request_terminal_rejected')]
    expected='rejected_terminal' if e['task_stream'][1]['release_at_ms']<e['exogenous_events'][0]['at_ms'] else 'admitted'
    for ok,msg in [(len(ae)==1,'admission event count'),(a['expected_admission']=={low:expected},'expected admission'),(a['observed_admission']=={low:expected},'observed admission'),(a['admission_correct']=={low:True},'admission correctness'),('correct_disposition' not in a,'legacy disposition metric')]:
        if not ok:d['execution_scoring_errors'].append(msg)
    for k in ['task_correct_action_completed','task_completion_latency_ms','task_deadline_met']:
        if a[k]!=d['computed'][k]:d['execution_scoring_errors'].append('audit.'+k)
    d['section']='runs' if i<32 else 'diagnostics';d['section_index']=i if i<32 else i-32;d['case']=r.get('case');d['admission_event_indices']=[j for j,x in ae]
    if i<32:
        for k in core:
            if r['result'][k]!=old['runs'][i]['result'][k]:d['execution_scoring_errors'].append('v5 regression '+k)
pairs=[]
for scene in ('LIGHT','BLINDS'):
    for policy in dict.fromkeys(r['policy'] for r in packet['runs']):
        rr=[(i,r) for i,r in enumerate(packet['runs']) if scene in r['evaluation_episode_id'] and r['policy']==policy]
        requests=[r['trace']['agent_requests'][0] for i,r in rr]
        pairs.append({'scene':scene,'policy':policy,'run_indices':[i for i,r in rr],'request_index':0,'full_input_equal':all(q==requests[0] for q in requests)})
frozen={}
for name,h in {'protection_v5_inputs.json':'dfc7b9ca310cbcc993a33af4aa2720ec3e63ff6b07ab18847730f92c3dc5bfd3','protection_v5_manifest.json':'88a99bca9c8c68a8a8a4267c157e09dc4356c0ccfd429c960ca1ab522759d2c3'}.items():frozen[name]=sha(ROOT/'homecoord_bench/task_revision/fixtures'/name)==h
frozen['protection_v5_offline_20261002.json']=sha(ROOT/'homecoord_bench/results/protection_v5_offline_20261002.json')=='361aa9078cf0344399271c60826f0d864058ca82258658ed2f7bc053566f8d0c'
sys.path.insert(0,str(ROOT))
from homecoord_bench.task_revision.protection_revision_v6 import run,audit,bundle
from homecoord_bench.task_revision.milestone import FixedProposals
probes=[]
class Capture(FixedProposals):
    def __init__(self):super().__init__();self.seen=[];self.instructions=[]
    def decide(self,request,*args,**kwargs):self.seen.append(copy.deepcopy(request));self.instructions.append(args[0] if args else kwargs.get('instructions'));return super().decide(request,*args,**kwargs)
for scene in ('LIGHT','BLINDS'):
    base=episodes['C1R3-'+scene+'-legality-SAFE']
    for policy in dict.fromkeys(r['policy'] for r in packet['runs']):
        c=Capture();rr=run(base,policy,c)
        changed=copy.deepcopy(base);changed['episode_id']='PRIVATE-CONFLICT-equal_response';changed['base_episode_id']='PRIVATE-SAFE-legality';changed['variant']='PRIVATE';changed['exogenous_events'][0]['at_ms']=6100;changed['task_stream'][1]['release_at_ms']=6600
        cc=Capture();ss=run(changed,policy,cc)
        probes.append({'scene':scene,'policy':policy,'provider_trace_equal':c.seen==rr['trace']['agent_requests'],'instructions_empty':all(s=='' for s in c.instructions+cc.instructions),'private_id_and_future_counterfactual_equal':c.seen[0]==cc.seen[0],'original_trace':rr['trace'],'counterfactual_trace':ss['trace']})
class Hook(Capture):
    invoked=False
    def prepare_release_batch(self,*a,**kw):self.invoked=True
h=Hook()
try:run(base,provider=h);hook=False
except ValueError:hook=not h.invoked and not h.seen
tamper=[]
r=packet['runs'][4];e=episodes[r['evaluation_episode_id']]
idx=next(i for i,x in enumerate(r['trace']['events']) if x['type']=='request_admitted')
for mode in ('delete','duplicate'):
    t=copy.deepcopy(r['trace'])
    if mode=='delete':t['events'].pop(idx)
    else:t['events'].insert(idx,copy.deepcopy(t['events'][idx]))
    try:audit(e,t,r['result']);rejected=False
    except AssertionError:rejected=True
    tamper.append({'mode':mode,'source_run_index':4,'source_event_index':idx,'audit_rejected':rejected})
reproduced=bundle()
reproduction={p:read(ROOT/p)==data for p,data in reproduced.items()}
old_manifest=read(ROOT/'homecoord_bench/task_revision/fixtures/protection_v5_manifest.json')
for name,h in old_manifest['source_sha256'].items():frozen[name]=sha(ROOT/'homecoord_bench/task_revision'/name)==h
request_strings=[]
for section in ('runs','diagnostics'):
    for i,r in enumerate(packet[section]):
        for j,q in enumerate(r['trace']['agent_requests']):
            text=json.dumps(q,ensure_ascii=False)
            found=[tag for tag in ('C1R2','C1R3','CONFLICT','SAFE','legality','equal_response','exogenous_events','task_stream','task_card','review_status') if tag in text]
            if found:request_strings.append({'section':section,'index':i,'request_index':j,'labels':found})
out={'hash_errors':hash_errors,'v5_frozen_artifacts':frozen,'full_first_request_pairs':pairs,'runs_and_diagnostics':details,'runtime_probes':probes,'hook_rejected_before_invocation':hook,'admission_event_tampering':tamper,'full_payload_label_findings':request_strings,'saved_bundle_reproduction':reproduction}
(OUT/'C1_V6_TARGETED_AUDIT_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hash_errors':hash_errors,'frozen':frozen,'errors':[(d['section'],d['section_index'],d['execution_scoring_errors']) for d in details if d['execution_scoring_errors']],'leaks':sum(len(d['input_channel_findings']) for d in details),'pairs_equal':sum(p['full_input_equal'] for p in pairs),'runtime_pairs_equal':sum(p['private_id_and_future_counterfactual_equal'] for p in probes),'provider_trace_equal':sum(p['provider_trace_equal'] for p in probes),'hook':hook,'tamper':tamper,'diagnostics':[{'index':d['section_index'],'policy':d['policy'],'case':d['case'],'computed':d['computed'],'events':d['evidence']} for d in details[32:]]},ensure_ascii=False,indent=2))
