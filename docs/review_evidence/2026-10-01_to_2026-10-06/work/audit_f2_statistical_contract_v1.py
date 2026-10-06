import json,hashlib,copy,itertools,sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs');F=R/'homecoord_bench/task_revision/fixtures/f2_v7';B=R/'docs/f2_statistical_contract_v1_20261004'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,s):checks.append({'check':s,'passed':bool(v)})
def diff(a,b,p=''):
    if type(a)!=type(b):return [p]
    if isinstance(a,dict):return sum([diff(a.get(k),b.get(k),p+'/'+k) for k in sorted(a.keys()|b.keys())],[])
    if isinstance(a,list):return [p] if len(a)!=len(b) else sum([diff(x,y,p+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b))],[])
    return [] if a==b else [p]
plan=read(B/'plan.json');es={e['episode_id']:e for e in read(F/'inputs.json')['episodes']};idx=read(F/'index.json');manifest=read(F/'manifest.json')
old=read(O/'F2_STATISTICAL_SCOPE_DRAFT_20261004.json')
for p,h in old['scope_hashes'].items():ck(sha(R/p)==h,'prior independent input index manifest snapshot '+p)
ck(set(plan['source_sha256'])=={str((F/'manifest.json').relative_to(R)).replace('\\','/'),*manifest['artifact_sha256']},'exact24source locks')
for p,h in plan['source_sha256'].items():ck(sha(R/p)==h,'plan source lock '+p)
for p,h in manifest['source_sha256'].items():ck(sha(R/p)==h,'original source code lock '+p)
author=read(B/'author_verification.json')
for p,h in author['protected_sha256'].items():ck(sha(R/p)==h,'author protection lock '+p)
ck(len(author['protected_sha256'])==164,'164 declared protected files')
ck(sha(Path(author['source_review_path']))==author['source_review_sha256'],'actual prior independent F2 review')
for auditname in ('F1_AGGREGATION_V1_AUDIT_20261004.json','F1_CONTRACT_V2_CORRECTION_AUDIT_20261004.json'):
    for p,h in read(O/auditname)['reviewed_sha256'].items():ck(sha(R/p)==h,'previous independently saved hash '+p)
config={c['episode_id']:c for c in plan['configurations']};P=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule');bases=('D-F2-01','D-F2-02');arms=('competition','no_competition');arrivals=('simultaneous','late')
ck(len(config)==8 and set(config)==set(es),'eight exact configurations')
lookup={};identities=[]
for eid,e in es.items():
    c=config[eid];tasks=e['task_stream'];g={x['task_id']:x for x in e['action_grounding'] if x['operation']=='prepare'}
    req=[{'task_id':t['task_id'],'deadline_ms':t['completion_deadline_ms'],'release_at_ms':t['release_at_ms'],'requested_service':t['requested_service'],'modes':[{'operation':'prepare','duration_ms':g[t['task_id']]['duration_ms'],'resource_units':g[t['task_id']]['power_kw']}]} for t in tasks]
    ctx=e['initial_state']['values']['coordination_context'];ck(ctx['requests']==[r for r in req if r['release_at_ms']==0] and ctx['resource_capacity_units']==e['home']['resources']['max_power_kw'],eid+' exact initial published context')
    future=[r for r in req if r['release_at_ms']>0]
    ev=[{'event':'new_public_request','at_ms':future[0]['release_at_ms'],'patch':{'coordination_context':{**ctx,'requests':req}}}] if future else []
    ck(e['exogenous_events']==ev,eid+' exact exogenous publication')
    required=[{**{k:t[k] for k in ('task_id','agent_id','release_at_ms','completion_deadline_ms','requested_service','acceptable_actions')},'service_window_ms':t['completion_deadline_ms']-t['release_at_ms']} for t in tasks]
    ck(c['required_requests']==required and len(required)==4 and c['early_task_ids']==[t['task_id'] for t in tasks[:-1]] and c['arrival_task_ids']==['water'],eid+' static four E and three early one water')
    ck(all(t['release_at_ms']==0 for t in tasks[:-1]) and tasks[-1]['task_id']=='water',eid+' early subset invariant')
for r in plan['runs']:
    d=read(R/r['source_path'])['runs'][int(r['source_pointer'].split('/')[-1])]
    ck((d['evaluation_episode_id'],d['policy'])==(r['episode_id'],r['policy']),r['slot_id']+' exact source row identity')
    ck(r['source_path'] in idx['run_files'] and r['required_set_ref']==r['episode_id'],r['slot_id']+' index primary role')
    lookup[(r['episode_id'],r['policy'])]=r['slot_id'];identities.append({'slot':r['slot_id'],'source':r['source_path'],'pointer':r['source_pointer'],'verdict':'符合计划'})
ck(len(plan['runs'])==len(set(r['slot_id'] for r in plan['runs']))==len(lookup)==32,'32unique primary slots')
exp=[]
def pair(k,a,b):exp.append({'kind':k,'left':a,'right':b,'delta':'right_minus_left'})
for eid in sorted(es):
    for p in P[1:]:pair('policy',lookup[(eid,P[0])],lookup[(eid,p)])
    for p in P[1:3]:pair('strong_rule',lookup[(eid,P[3])],lookup[(eid,p)])
groups=[];contrasts=[]
for base in bases:
    for timing in arrivals:
        a,b=(f'F2R1-{base}-{arm}-{timing}' for arm in arms);contrasts.append(('capacity',a,b))
        for p in P:pair('capacity',lookup[(a,p)],lookup[(b,p)])
    for arm in arms:
        a,b=(f'F2R1-{base}-{arm}-{t}' for t in arrivals);contrasts.append(('release',a,b))
        for p in P:pair('release',lookup[(a,p)],lookup[(b,p)])
    for p in P:groups.append({'base_episode_id':base,'policy':p,'slots':[lookup[(f'F2R1-{base}-{a}-{t}',p)] for a,t in itertools.product(arms,arrivals)],'cell_order':['tight_simultaneous','tight_late','adequate_simultaneous','adequate_late'],'metric_rules_ref':'/metric_rules'})
ck(exp==plan['pairs'] and len(exp)==72 and len({(p['kind'],p['left'],p['right']) for p in exp})==72,'all72pairs reconstructed direction kind endpoints')
ck(groups==plan['four_cells'] and len(groups)==8,'all8fourcells rebuilt with fixed order')
for kind,a,b in contrasts:
    ea,eb=es[a],es[b];x,y=copy.deepcopy(ea),copy.deepcopy(eb)
    for e in (x,y):
        e.pop('episode_id');e['pairing'].pop('resource_arm' if kind=='capacity' else 'temporal_arm')
        if kind=='capacity':
            e['home']['resources'].pop('max_power_kw');e['initial_state']['values']['coordination_context'].pop('resource_capacity_units')
            for ev in e['exogenous_events']:ev['patch']['coordination_context'].pop('resource_capacity_units')
            for cr in e['conflict_rules']:
                if cr['type']=='C3':cr.pop('capacity')
        else:
            # These redundant structures were fully checked above, not blindly discarded.
            e['initial_state']['values']['coordination_context'].pop('requests');e.pop('exogenous_events')
            for t in e['task_stream']:
                if t['task_id']=='water':t['completion_deadline_ms']-=t['release_at_ms'];t['release_at_ms']=0
    ck(x==y,kind+a+' only authorized intervention after exact redundancy checks')
    row=next(c for c in plan['contrast_checks'] if c['kind']==kind and c['left_config']==a)
    ck(row['right_config']==b and row['actual_changed_paths']==diff(ea,eb),kind+a+' full actual difference paths')
    wa,wb=ea['task_stream'][-1],eb['task_stream'][-1]
    if kind=='release':ck(wb['release_at_ms']-wa['release_at_ms']==(60000 if ea['base_episode_id']=='D-F2-01' else 120000) and wa['completion_deadline_ms']-wa['release_at_ms']==wb['completion_deadline_ms']-wb['release_at_ms'],a+' release deadline shift preserves own budget')
    else:ck((ea['home']['resources']['max_power_kw'],eb['home']['resources']['max_power_kw'])==(3,6),a+' capacity3to6')
diags={r['slot_id']:r for r in plan['diagnostic_runs']};ck(len(diags)==len(plan['diagnostic_runs'])==48,'48unique diagnostic slots')
ck(set(r['source_path'] for r in diags.values())==set(idx['diagnostic_files']),'all only12 diagnostic source files')
for p in plan['diagnostic_prefix_pairs']:
    d=diags[p['diagnostic_slot']];packet=read(R/d['source_path']);i=int(d['source_pointer'].split('/')[-1]);policy=packet['runs'][i]['policy'];main=next(r for r in plan['runs'] if r['slot_id']==p['main_slot']);L=es[main['episode_id']]['task_stream'][-1]['release_at_ms']
    ck(d['policy']==main['policy']==policy and d['case']==packet['case'] and L==p['before_ms']==packet['before_ms'] and not p['performance_pair'] and not d['in_main_service_denominator'],'diag '+d['slot_id']+' correct main policy cutoff role')
    ck(p['comparison']=='full_calls_requests_and_decisions_and_events_strict_timestamp_less_than_cutoff','diag '+d['slot_id']+' strict complete prefix rule')
rules=plan['metric_rules']
ck(rules['time_origin']=='each_tasks_own_release_not_episode_time' and rules['four_cell_time_K']=='intersection_of_valid_completed_task_ids_in_all_four_cells','own release clock and common fourK')
ck(rules['empty_K']=='null: no_common_completed_requests' and rules['missing_metric_on_K_or_missing_slot']=='data_error_not_reweight_or_drop_or_zero' and rules['own_C_means_and_conditional_rates_in_four_cell_interaction'] is False,'null missing and conditional eligibility')
ck(rules['macro_weights']=={'per_policy_per_template_slots':4,'slot_weight':'1/4','template_weight':'1/2','metrics':['service_rate','timely_service_rate'],'skip_missing':False},'four slots two templates fixedE mainrates only')
ck(not rules['reservation_is_actual_resource_load'] and not rules['diagnostics_in_service_denominator'] and rules['arrival_resource_snapshot']=='descriptive_not_causal_not_unavoidable' and rules['unlisted_four_cell_metrics']=='not_eligible','reservation diagnostic snapshot scope and white-list')
sys.path.insert(0,str(R));from homecoord_bench.task_revision.f2_statistical_contract_v1 import bundle
ck(bundle()==plan,'author metadata reproduces after independent reconstruction')
files=[R/'docs/F2_STATISTICAL_CONTRACT_V1_2026-10-04.md',R/'docs/F2_STATISTICAL_CONTRACT_V1_REVIEW_PACKET_2026-10-04.md',R/'homecoord_bench/task_revision/f2_statistical_contract_v1.py',R/'homecoord_bench/tests/test_f2_statistical_contract_v1.py',B/'plan.json',B/'author_verification.json']
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'run_identity_checks':identities,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'scoped_tests':{'actual_run':10,'result':'OK','author51_not_claimed_as_review51':True,'full_suite_rerun':False},'actual_strategy_scores_read_or_computed':False,'adapter_reviewed':False,'freeze_performed':False}
(O/'F2_STATISTICAL_CONTRACT_V1_AUDIT_20261004.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'checks':len(checks),'errors':out['errors'],'runs':32,'pairs':len(exp),'fourcells':len(groups),'diagnostics':len(diags)},ensure_ascii=False))
