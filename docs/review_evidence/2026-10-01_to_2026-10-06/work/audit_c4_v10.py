import json,copy,hashlib,sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');B=R/'homecoord_bench/task_revision/fixtures/c4_v10';V9=R/'homecoord_bench/task_revision/fixtures/c4_v9'
sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
# Reuse the reviewer's v9 reconstruction, not the author's audit. Its existing
# invalid-attempt latch is reconstructed from state and time, independently of
# the new attempt_invalidated event name. Extend physical-end serialization.
source=Path('work/audit_c4_v9.py').read_text(encoding='utf-8')
source=source[source.index('def expected_input'):source.index('details=[];packets={}')]
source=source.replace('physical={};cancelled=', 'physical={};invalid_physical={};cancelled=')
source=source.replace("('action_stopped','action_completed','withdrawn_action_physically_completed')", "('action_stopped','action_completed','withdrawn_action_physically_completed','invalidated_action_physically_completed')")
needle="                else:\n                    ck(tid not in withdrawn and pid not in cancelled,f'e{j} forbidden service receipt')"
replacement="""                elif kind=='invalidated_action_physically_completed':
                    ck(pid in invalid_attempts and cs[tid]['mode']=='restart_from_zero',f'e{j} invalid physical qualification')
                    effects={p:v for p,v in effects.items() if not p.startswith('service.')}
                    invalid_physical[pid]={'task_id':tid,'proposal_id':pid,'timestamp_ms':now,'invalid_since_ms':onsets[pid]}
                else:
                    ck(tid not in withdrawn and pid not in cancelled,f'e{j} forbidden service receipt')"""
assert needle in source;source=source.replace(needle,replacement)
source=source.replace("'physical_completions_after_withdrawal':list(physical.values())", "'physical_completions_after_invalidation':list(invalid_physical.values()),'physical_completions_after_withdrawal':list(physical.values())")
source=source.replace("        if kind=='stop_requested':", "        if kind=='attempt_invalidated':ck(pid in invalid_attempts and pid in active and onsets[pid]==now and cs[tid]['mode']=='restart_from_zero',f'e{j} invalidation evidence')\n        if kind=='stop_requested':")
helpers=Path('work/audit_c4_v9.py').read_text(encoding='utf-8');exec(helpers[helpers.index('def get('):helpers.index('main=read(')])
exec(source)
from homecoord_bench.task_revision.c4_revision_v9 import PublicC4
from homecoord_bench.task_revision.c4_revision_v10 import bundle
from homecoord_bench.task_revision.event_simulator_v10 import run_event_simulation
from homecoord_bench.task_revision.c4_audit_v10 import audit as author_audit
class Capture(PublicC4):
    def __init__(self,latency=300):super().__init__(latency);self.instructions=[]
    def decide(self,q,instructions):self.instructions.append(instructions);return super().decide(q,instructions)
def rerun(e,p,latency=300):
    c=Capture(latency);tr,res=run_event_simulation(e,c,p,'',shared_safety_gate=True)
    return {'policy':p,'trace':tr,'result':res,'calls':c.calls,'audit':author_audit(e,tr,res,c.calls),'declared_proposal_latency_ms':latency},all(x=='' for x in c.instructions)
details=[];captures=[];target_runs={}
for case in read(B/'inputs.json')['cases']:
    name=case['case'];e=case['episode'];file=f'homecoord_bench/task_revision/fixtures/c4_v10/runs/{name}.json'
    for i,saved in enumerate(read(R/file)['runs']):
        r=copy.deepcopy(saved);r['declared_proposal_latency_ms']=300
        details.append(audit(e,r,file,i,'target'))
        fresh,empty=rerun(e,r['policy']);captures.append({'case':name,'policy':r['policy'],'saved_trace_result_calls_audit_equal':all(fresh[k]==r[k] for k in ('trace','result','calls','audit')),'instructions_empty':empty})
        target_runs[name,i]=(e,fresh)
oldidx=read(V9/'index.json');episodes={e['episode_id']:e for e in read(V9/'inputs.json')['episodes']}
episodes.update({x['episode']['episode_id']:x['episode'] for x in read(V9/'diagnostic_inputs.json')['cases']})
submitted={(x['episode_id'],x['policy']):x for x in read(B/'regression.json')['checks']}
regressions=[];old_rejections=[];runtime={}
for file in oldidx['run_files']+oldidx['diagnostic_files']:
    for i,previous in enumerate(read(R/file)['runs']):
        e=episodes[previous['evaluation_episode_id']];r,empty=rerun(e,previous['policy'],previous['declared_proposal_latency_ms']);runtime[e['episode_id'],i]=r
        d=audit(e,r,'runtime:'+file,i,'regression');details.append(d)
        delta={k:{'old':previous['result'].get(k),'new':r['result'].get(k)} for k in sorted(set(previous['result'])|set(r['result'])) if previous['result'].get(k)!=r['result'].get(k)}
        declared=submitted[e['episode_id'],r['policy']];affected=e['episode_id']=='C4R1-CLEAN-LATE-late_natural_race'
        regressions.append({'episode_id':e['episode_id'],'run_index':i,'policy':r['policy'],'affected':affected,'calls_equal':r['calls']==previous['calls'],'result_equal':r['result']==previous['result'],'declared_difference_and_audit_equal':declared['changed_result_fields']==delta and declared['audit']==r['audit'],'instructions_empty':empty,'changed_fields':list(delta)})
        if affected:
            try:author_audit(e,previous['trace'],previous['result'],previous['calls']);rejected=False
            except AssertionError:rejected=True
            old_rejections.append({'policy':r['policy'],'old_v9_rejected':rejected})
controls=[]
for scene in ('CLEAN','RAIN'):
    tid=episodes[f'C4R1-{scene}-MID']['task_stream'][0]['task_id']
    for i in range(4):
        x=runtime[f'C4R1-{scene}-MID',i];y=runtime[f'C4R1-{scene}-MID-local_only',i]
        controls.append({'scene':scene,'run_index':i,'equal':x['audit']['response_records']==y['audit']['response_records'] and x['audit']['harm_duration_ms']==y['audit']['harm_duration_ms'] and all(x['audit']['service_recount'][k][tid]==y['audit']['service_recount'][k][tid] for k in x['audit']['service_recount'])})
forgeries=[]
for name in ('late_race','restore_before_natural_end'):
    for i in range(4):
        e,r=target_runs[name,i];bad=copy.deepcopy(r)
        # A forged ordinary receipt must be rejected even after validity restores.
        x=next(x for x in bad['trace']['events'] if x['type']=='invalidated_action_physically_completed');x['type']='action_completed';x['effects']['service.work_completed']=True
        bad['trace']['events']=[x for x in bad['trace']['events'] if x['type']!='attempt_invalidated']
        try:author_audit(e,bad['trace'],bad['result'],bad['calls']);rejected=False;message=None
        except AssertionError as exc:message=str(exc);rejected='invalid attempt' in message
        ours=audit(e,bad,'forgery',i,'negative')
        forgeries.append({'case':name,'run_index':i,'attempt_invalidated_markers_removed':True,'author_rejected':rejected,'author_rejection_message':message,'reviewer_invalid_attempt_detected':bool(ours['contract_errors'])})
hash_checks=[]
m=read(B/'manifest.json')
for section in ('source_sha256','artifact_sha256','v9_frozen_sha256'):
    for path,h in m[section].items():hash_checks.append({'section':section,'path':path,'equal':sha(R/path)==h})
prior=read(O/'C4_V9_EVENT_AUDIT_20261003.json');hash_checks.append({'section':'prior_independent_v9_manifest','path':str((V9/'manifest.json').relative_to(R)),'equal':sha(V9/'manifest.json')==prior['manifest_sha256']})
for section in ('source_sha256','artifact_sha256'):
    for path,h in read(V9/'manifest.json')[section].items():hash_checks.append({'section':'prior_v9_manifest_'+section,'path':path,'equal':sha(R/path)==h})
reproduction={p:read(R/p)==v for p,v in bundle().items()}
out={'manifest_sha256':sha(B/'manifest.json'),'details':details,'captures':captures,'regressions':regressions,'local_controls':controls,'old_rejections':old_rejections,'forgeries':forgeries,'hash_checks':hash_checks,'bundle_reproduction':reproduction,'scoped_tests':{'module':'homecoord_bench.tests.test_c4_v10','tests':10,'failures':0,'errors':0,'full476_not_run':True}}
(O/'C4_V10_EVENT_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'runs':len(details),'target_runs':len(captures),'findings':[{'id':d['episode_id'],'run':d['run_index'],'errors':d['errors'],'contract_errors':d['contract_errors']} for d in details if d['errors'] or d['contract_errors']],'capture28':all(x['saved_trace_result_calls_audit_equal'] for x in captures),'calls96':all(x['calls_equal'] for x in regressions),'unchanged92':sum(x['result_equal'] for x in regressions),'declared_regression96':all(x['declared_difference_and_audit_equal'] for x in regressions),'local8':all(x['equal'] for x in controls),'old_v9_rejected4':all(x['old_v9_rejected'] for x in old_rejections),'forgeries_rejected8':all(x['author_rejected'] and x['reviewer_invalid_attempt_detected'] for x in forgeries),'hash_errors':[x for x in hash_checks if not x['equal']],'reproduction10':all(reproduction.values())},ensure_ascii=False,indent=2))
