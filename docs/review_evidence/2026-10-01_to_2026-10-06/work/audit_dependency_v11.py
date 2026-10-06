import json,copy,hashlib,sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');B=R/'homecoord_bench/task_revision/fixtures/dependency_v11';sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
# Reviewer's own prior event reconstruction. Adapt the validity polarity and
# public contract, add dependency guards and derive scores from valid attempts.
bootstrap=Path('work/audit_c4_v10.py').read_text(encoding='utf-8');exec(bootstrap[bootstrap.index('# Reuse'):bootstrap.index('from homecoord_bench.task_revision.c4_revision_v9')])
source=source.replace("x['patch'].get(signal) is True", "x['patch'].get(signal) is False")
source=source.replace("cs[tid]['mode']=='restart_from_zero',f'e{j} invalidation evidence'", "cs[tid]['mode'] in ('restart_from_zero','withdraw'),f'e{j} invalidation evidence'")
source=source.replace("effects={p:v for p,v in effects.items() if not p.startswith('service.')}", "effects={p:v for p,v in effects.items() if p.startswith('devices.')}")
source=source.replace("physical={};invalid_physical={};cancelled=", "physical={};invalid_physical={};depwaiting=set();depblocked=set();cancelled=")
source=source.replace("        if kind=='action_started':", """        if kind=='dependency_waiting':
            ck(any(d not in done for d in tasks[tid]['depends_on']) and not any(d in withdrawn for d in tasks[tid]['depends_on']),f'e{j} dependency wait reason');depwaiting.add(tid)
        if kind=='dependency_ready':
            ck(all(d in done and d not in withdrawn for d in tasks[tid]['depends_on']),f'e{j} fake dependency ready');depwaiting.discard(tid)
        if kind=='dependency_blocked':
            ck(any(d in withdrawn or d in depblocked for d in tasks[tid]['depends_on']),f'e{j} false dependency block');depwaiting.discard(tid);depblocked.add(tid)
        if kind=='action_started':
            for predecessor in tasks[tid].get('depends_on',[]):
                ck(predecessor in done and predecessor not in withdrawn and e['batch_binding'][tid]==e['batch_binding'][predecessor],f'e{j} trusted predecessor receipt')
                ck(predecessor in done and now>=done.get(predecessor,now)+100,f'e{j} dependency command confirmation')
""")
source=source.replace("    ck(state['service']['work_completed']==any(tid in done for tid in cs),'work receipt not supported by valid completion')", """    for t in tasks:
        ck(state['service'][t+'_completed']==(t in done),'work receipt not supported by valid completion '+t)
    ck(set(res['dependency_completed_receipts'])==set(done),'trusted receipt summary')
    ck(set(res['dependency_waiting_task_ids'])==depwaiting,'dependency waiting summary')
    ck(set(res['dependency_blocked_task_ids'])==depblocked,'dependency blocked summary')
    ck(depblocked=={t for t in tasks if any(d in withdrawn for d in tasks[t].get('depends_on',[]))},'terminal cancellation propagation')
    ck(res['task_unstarted_count']==len(tasks)-len(starts) and res['task_incomplete_count']==len(tasks)-len(done),'incomplete counts')
    ck(res['task_service']=={t:t in done for t in tasks} and res['served_task_count']==len(done),'service aggregates')
    ck(res['task_service_rate']==len(done)/len(tasks),'service rate')
    ck(res['task_action_finish_time_ms']=={t:done.get(t) for t in tasks},'absolute task finish aliases')
    ck(res['final_goal_success']==all(holds(state,g) for g in e['goals']),'final goal state')
    computed['trusted_dependency_receipts_ms']=done
    ck(r['audit']['trusted_dependency_receipts_ms']==done,'author trusted receipts')
""")
source=source.replace("'invalid_attempts':sorted(invalid_attempts)", "'invalid_attempts':sorted(invalid_attempts),'dependency_waiting':sorted(depwaiting),'dependency_blocked':sorted(depblocked)")
exec(source)
base_expected=expected_input
def expected_input(e,t,policy,ss,version):
    fake=copy.deepcopy(e);fake['c4_scene']='CLEAN';q=base_expected(fake,t,policy,ss,version)
    q.update(request_id=f'HC-M12:{policy}:{t["task_id"]}',episode_id='HC-M12',base_episode_id='HC-M12')
    q['task']['goal']='Execute authorized service for the declared batch; trusted completion gates prerequisites.';q['task']['batch_id']=e['batch_binding'].get(t['task_id'])
    return q
from homecoord_bench.task_revision.dependency_revision_v11 import Provider,bundle
from homecoord_bench.task_revision.event_simulator_v11 import run_event_simulation
from homecoord_bench.task_revision.dependency_audit_v11 import audit as author_audit
es=read(B/'inputs.json')['episodes'];details=[];captures=[];savedruns={};runtime={};injections=[];canaries=[];pairs=[];negatives=[]
class Capture(Provider):
    def __init__(self,inject=False):super().__init__(inject);self.instructions=[]
    def decide(self,q,instructions):self.instructions.append(instructions);return super().decide(q,instructions)
def rerun(e,p,inject=False):
    c=Capture(inject);tr,res=run_event_simulation(e,c,p,'',shared_safety_gate=True)
    return {'policy':p,'trace':tr,'result':res,'calls':c.calls,'audit':author_audit(e,tr,res,c.calls)},all(x=='' for x in c.instructions)
for e in es:
    name=e['nominal_window'];file=f'homecoord_bench/task_revision/fixtures/dependency_v11/runs/{name}.json'
    for i,saved in enumerate(read(R/file)['runs']):
        savedruns[name,i]=saved;r=copy.deepcopy(saved);r['declared_proposal_latency_ms']=300
        details.append(audit(e,r,file,i,'main'))
        fresh,empty=rerun(e,r['policy'],name=='INVALID_PROPOSAL');runtime[name,i]=fresh
        captures.append({'configuration':name,'run_index':i,'saved_equal':fresh==saved,'instructions_empty':empty})
    changed=copy.deepcopy(e);changed['episode_id']='PRIVATE-future-case';changed['nominal_window']='PRIVATE-stage';changed['evaluation_class']='PRIVATE-class';changed['task_card']['private']='PRIVATE-answer';changed['authority']['basis']='PRIVATE-policy'
    for t in changed['task_stream']:t['goal']='PRIVATE-goal';t['action_template']['private']='PRIVATE-template'
    for tool in changed['tool_catalog']:tool['description']='PRIVATE-description'
    # Injected output is controlled explicitly, independent of private ID/class.
    x,_=rerun(e,'ConstraintCoordinator',name=='INVALID_PROPOSAL');y,_=rerun(changed,'ConstraintCoordinator',name=='INVALID_PROPOSAL')
    canaries.append({'configuration':name,'full_requests_equal':x['trace']['agent_requests']==y['trace']['agent_requests']})
for i in range(4):
    normal=savedruns['EARLY',i];bad=savedruns['INVALID_PROPOSAL',i];adjust=copy.deepcopy(bad['calls']);adjust[0]['decision']['actions'][0]['operation']='wash'
    injections.append({'run_index':i,'only_operation_changed':adjust==normal['calls'],'returned_at':next(x['timestamp_ms'] for x in bad['trace']['events'] if x['type']=='proposal_returned' and x['task_id']=='wash'),'rejections':[{'event_index':j,'time_ms':x['timestamp_ms'],'reason':x.get('reason')} for j,x in enumerate(bad['trace']['events']) if x['type']=='action_rejected' and x.get('task_id')=='wash']})
    for mode in ('CANCEL','RESTART'):
        x=savedruns[mode+'_NO_RESTORE',i];y=savedruns[mode+'_RESTORE',i];pairs.append({'mode':mode,'run_index':i,'calls_equal':x['calls']==y['calls']})
e=next(x for x in es if x['nominal_window']=='STALE_NATURAL_RACE')
for i in range(4):
    bad=copy.deepcopy(savedruns['STALE_NATURAL_RACE',i]);bad['trace']['events']=[x for x in bad['trace']['events'] if x['type']!='attempt_invalidated'];event=next(x for x in bad['trace']['events'] if x['type']=='invalidated_action_physically_completed');event['type']='action_completed';event['effects'].update({'laundry.washed':True,'service.wash_completed':True})
    try:author_audit(e,bad['trace'],bad['result'],bad['calls']);rejected=False;msg=None
    except AssertionError as exc:msg=str(exc);rejected='invalid attempt' in msg
    bad['declared_proposal_latency_ms']=300;own=audit(e,bad,'forgery',i,'negative')
    negatives.append({'case':'forged_valid_completion','run_index':i,'removed_invalidation_marker':True,'author_rejected':rejected,'reviewer_detected':bool(own['contract_errors']),'message':msg})
preflight=[];base=es[0]
for case in ('wrong_batch','world_service_receipt','future_hook','instructions','unsupported_policy','no_gate'):
    e=copy.deepcopy(base);c=Capture();p='ConstraintCoordinator';inst='';gate=True
    if case=='wrong_batch':e['batch_binding']['dry']='batch_2'
    elif case=='world_service_receipt':e['exogenous_events'][0]['patch']['service.wash_completed']=True
    elif case=='future_hook':c.prepare_release_batch=lambda *a,**k:None
    elif case=='instructions':inst='PRIVATE'
    elif case=='unsupported_policy':p='CentralSingleAgent'
    else:gate=False
    try:run_event_simulation(e,c,p,inst,shared_safety_gate=gate);ok=False;msg=None
    except ValueError as exc:ok=not c.calls;msg=str(exc)
    preflight.append({'case':case,'rejected_before_calls':ok,'message':msg})
m=read(B/'manifest.json');hash_checks=[]
for section in ('source_sha256','artifact_sha256'):
    for path,h in m[section].items():hash_checks.append({'reference':'v11 manifest','path':path,'equal':sha(R/path)==h})
oldmanifest=R/'docs/implementation_review_20261001/manifest.json';prior=read(O/'PHASE_B_EVENT_AUDIT.json')['summary']
hash_checks.append({'reference':'prior independent Phase B','path':str(oldmanifest.relative_to(R)),'equal':sha(oldmanifest)==prior['manifest_sha256']})
for section in ('source_sha256','artifact_sha256','historical_result_sha256'):
    for path,h in read(oldmanifest)[section].items():hash_checks.append({'reference':'frozen Phase B '+section,'path':path,'equal':sha(R/path)==h})
for version,priorfile in [('c4_v9','C4_V9_EVENT_AUDIT_20261003.json'),('c4_v10','C4_V10_EVENT_AUDIT_20261003.json')]:
    old=R/'homecoord_bench/task_revision/fixtures'/version/'manifest.json';prior=read(O/priorfile)
    hash_checks.append({'reference':'previous independent '+version,'path':str(old.relative_to(R)),'equal':sha(old)==prior['manifest_sha256']})
    for section in ('source_sha256','artifact_sha256','v9_frozen_sha256'):
        for path,h in read(old).get(section,{}).items():hash_checks.append({'reference':version+' manifest','path':path,'equal':sha(R/path)==h})
from homecoord_bench.task_revision.dependency_pilot import bundle as old_bundle
oldreproduction={p:read(R/p)==v for p,v in old_bundle().items()};reproduction={p:read(R/p)==v for p,v in bundle().items()}
out={'manifest_sha256':sha(B/'manifest.json'),'details':details,'captures':captures,'canaries':canaries,'input_pairs':pairs,'injections':injections,'forgeries':negatives,'preflight':preflight,'hash_checks':hash_checks,'v3_bundle_reproduction':oldreproduction,'v11_bundle_reproduction':reproduction,'scoped_tests':{'module':'homecoord_bench.tests.test_dependency_v11','tests':12,'failures':0,'errors':0,'full488_not_run':True}}
(O/'DEPENDENCY_V11_EVENT_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'runs':len(details),'findings':[{'id':d['episode_id'],'run':d['run_index'],'errors':d['errors'],'contract_errors':d['contract_errors']} for d in details if d['errors'] or d['contract_errors']],'captures52':all(x['saved_equal'] and x['instructions_empty'] for x in captures),'canaries13':all(x['full_requests_equal'] for x in canaries),'input_pairs8':all(x['calls_equal'] for x in pairs),'single_operation4':all(x['only_operation_changed'] for x in injections),'forgeries4':all(x['author_rejected'] and x['reviewer_detected'] for x in negatives),'preflight6':all(x['rejected_before_calls'] for x in preflight),'hash_errors':[x for x in hash_checks if not x['equal']],'old_reproduction':all(oldreproduction.values()),'v11_reproduction17':all(reproduction.values())},ensure_ascii=False,indent=2))
