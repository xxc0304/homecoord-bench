import json,copy,hashlib,sys,itertools
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs');B=R/'docs/small_validation_plan_v1_20261005'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,msg):checks.append({'check':msg,'passed':bool(v)})
def diff(a,b,p=''):
    if type(a)!=type(b):return [p]
    if isinstance(a,dict):return sum([diff(a.get(k),b.get(k),p+'/'+k) for k in sorted(a.keys()|b.keys())],[])
    if isinstance(a,list):return [p+'/length'] if len(a)!=len(b) else sum([diff(x,y,p+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b))],[])
    return [] if a==b else [p]
plan=read(B/'plan.json');add=read(B/'execution_statistics_addendum.json');author=read(B/'design_check_verification.json')
for p,h in author['protected_sha256'].items():ck(sha(R/p)==h,'author protection '+p)
ck(len(author['protected_sha256'])==217,'217 protection entries')
for p,h in read(O/'F2_AGGREGATION_V1_AUDIT_20261005.json')['reviewed_sha256'].items():ck(sha(R/p)==h,'prior independent F2 implementation lock '+p)
for p,h in plan['source_sha256'].items():ck(sha(R/p)==h,'plan frozen source '+p)
for p,h in plan['acceptance_sha256'].items():ck(sha(R/p)==h,'plan source acceptance '+p)
es=read(R/'homecoord_bench/task_revision/fixtures/f2_v7/inputs.json')['episodes']; sources={e['episode_id']:e for e in es if e['episode_id'].endswith('-late')};P=('GateRetryRule','ConstraintCoordinator','DeadlineAwareCoordinator')
expectedslots=[];expectedpairs=[];evidence=[];expectedconfigs=set()
for eid,s in sources.items():
    for factor,v in [('baseline',0),('water_budget_offset_ms',-30000),('water_budget_offset_ms',30000),('water_release_offset_ms',-30000),('water_release_offset_ms',30000),('command_latency_ms',0),('command_latency_ms',500)]:
        cid=f'{eid}|SV1|{factor}:{v}';expectedconfigs.add(cid);c=next(c for c in plan['configurations'] if c['config_id']==cid);e=copy.deepcopy(s);w=e['task_stream'][-1];oldbudget=w['completion_deadline_ms']-w['release_at_ms']
        if factor=='water_budget_offset_ms':w['completion_deadline_ms']+=v;w['goal']=w['goal'].replace('within '+str(oldbudget)+' ms','within '+str(oldbudget+v)+' ms')
        if factor=='water_release_offset_ms':w['release_at_ms']+=v;w['completion_deadline_ms']+=v;e['exogenous_events'][0]['at_ms']+=v
        if factor=='command_latency_ms':e['simulation']['command_latency_ms']=v
        public=e['exogenous_events'][0]['patch']['coordination_context']['requests'][-1];public['release_at_ms']=w['release_at_ms'];public['deadline_ms']=w['completion_deadline_ms']
        h=hashlib.sha256(json.dumps(e,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        ck(h==c['derived_episode_sha256'] and diff(s,e)==c['changed_paths_excluding_private_identity'],cid+' independent full input and difference paths')
        ck(c['source_episode_id']==eid and c['source_pointer']=='/episodes/'+str(es.index(s)),cid+' exact input pointer')
        req=[{'task_id':t['task_id'],'release_ms':t['release_at_ms'],'deadline_ms':t['completion_deadline_ms'],'own_budget_ms':t['completion_deadline_ms']-t['release_at_ms']} for t in e['task_stream']]
        ck(c['required_requests']==req and len(req)==4 and all(t['release_ms']==0 for t in req[:-1]) and req[-1]['task_id']=='water',cid+' fixed E early and water')
        ck(not any(t['task_id']=='water' for t in e['initial_state']['values']['coordination_context']['requests']),cid+' no future request in early public context')
        g={x['task_id']:x for x in e['action_grounding'] if x['operation']=='prepare'};ts={t['task_id']:t for t in e['task_stream']};ints=c['feasibility_certificate']['intervals'];cert=c['feasibility_certificate']
        ck(len(ints)==4 and {x['task_id'] for x in ints}==set(ts),cid+' certificate exact service coverage')
        for it in ints:
            tid=it['task_id'];ck(it['units']==g[tid]['power_kw'] and it['end_ms']-it['start_ms']==g[tid]['duration_ms'] and it['start_ms']>=ts[tid]['release_at_ms']+300+e['simulation']['command_latency_ms'] and it['end_ms']<=ts[tid]['completion_deadline_ms'],cid+' witness '+tid+' costs release command deadline')
        bounds=sorted({v for it in ints for v in (it['start_ms'],it['end_ms'])});cap=e['home']['resources']['max_power_kw']
        ck(all(sum(it['units'] for it in ints if it['start_ms']<=a<it['end_ms'])<=cap for a,b in zip(bounds,bounds[1:])),cid+' half-open resource feasibility')
        ck(cert['proposal_offset_ms']==300 and cert['command_latency_ms']==e['simulation']['command_latency_ms'] and c['command_latency_ms']==e['simulation']['command_latency_ms'] and c['capacity_units']==cap,cid+' clock and capacity metadata')
        earliest=min(t['release_at_ms']+300+e['simulation']['command_latency_ms']+g[t['task_id']]['duration_ms'] for t in e['task_stream'] if t['task_id']!='water')
        ck(0<w['release_at_ms']<earliest,cid+' release is strictly before theoretical first early completion')
        for policy in P:
            sid=cid+'|'+policy;expectedslots.append({'slot_id':sid,'config_id':cid,'policy':policy,'role':'main'})
            if factor!='baseline':expectedpairs.append({'left':eid+'|SV1|baseline:0|'+policy,'right':sid,'factor':factor,'delta_direction':'right_minus_left'})
        evidence.append({'config_id':cid,'source_episode_id':eid,'certificate_verdict':'符合设计','water_release_ms':w['release_at_ms'],'earliest_possible_early_completion_ms':earliest,'changes':diff(s,e)})
ck(len(expectedconfigs)==len(plan['configurations'])==28 and set(c['config_id'] for c in plan['configurations'])==expectedconfigs,'28 exact unique configurations')
ck(expectedslots==plan['run_slots'] and len(expectedslots)==84,'84 exact unique run slots')
ck(expectedpairs==plan['pairs'] and len(expectedpairs)==72,'72 exact baseline-to-perturbation pairs')
ck(add['fixed_populations']['denominators']=={'main':4,'early':3,'water':1},'fixed denominators4 3 1')
ck(add['time_allowlist']==['task_start_wait_ms','proposal_to_start_ms','execution_ms','completion_latency_ms','tardiness_ms'] and add['paired_scalar_allowlist']==add['primary_rates']+add['process_allowlist']+['whole_house_completion_ms'],'explicit scalar and time whitelist')
mr=add['missing_rules'];ck(mr['empty_K']=='retain_pair_metrics_null_no_common_completed_requests' and mr['missing_metric_on_K']=='hard_error_not_remove_task' and mr['whole_house_pair']=='both_arms_all_E_else_delta_null','K null metric and wholeE rules')
ck(not any(add['comparison'][k] for k in ('conditional_timely_rate_in_pair_allowlist','own_completed_mean_in_pair_allowlist','cross_config_macro','cross_family_pooling','factorial_interactions','ranking','statistical_independence_claim')),'no conditional substitute macro factorial or ranking')
be=add['baseline_equivalence'];ck(be['baseline_slot_count']==12 and be['all_fresh_baselines_required'] and be['public_identifier_normalization']=='none_expected_F2_public_home_identical' and be['baseline_mismatch']=='block_entire_batch_do_not_rename_or_refresh_baseline','12 fresh baseline exact public identity and wholebatch stop')
ck(be['compare_exact']==['calls_including_complete_request_and_decision','trace_agent_requests','trace_events_in_original_order_with_all_fields','trace_final_state','trace_final_state_version','trace_event_count','reviewed_event_derived_task_metrics_denominators_subsets_and_arrival_background'],'complete baseline comparison surface')
ck(be['trace_metadata_allowed_to_change']==['trace_id','episode_id'] and be['run_metadata_allowed_to_change']==['evaluation_episode_id','new_config_slot_manifest_identifiers'],'only private outer trace and run metadata mask')
runtime=(R/'homecoord_bench/task_revision/event_simulator_v7.py').read_text(encoding='utf-8')
for key,v in [('STATE_OR_COMPLETION',0),('TASK_RELEASE',1),('PROPOSAL_RESPONSE',3),('ACTION_START',4)]:ck(f'_PRIORITY_{key} = {v}' in runtime,'declared queue phase '+key)
ck('start = now_ms + int(episode.get("simulation", {}).get("command_latency_ms", DEVICE_DELAY_MS))' in runtime,'command lower bound at candidate dispatch')
ck(add['logical_clock']['command_latency_levels_ms']==[0,100,500] and add['logical_clock']['minimum_initial_start']=='S>=P+command_latency_ms' and add['logical_clock']['minimum_retry_start']=='S>=matching_retry_reservation_creation_time+command_latency_ms','initial retry lowerbound semantics')
files=[R/'docs/SMALL_VALIDATION_PLAN_V1_2026-10-05.md',R/'docs/SMALL_VALIDATION_V1_DESIGN_CHECK_AND_REVIEW_PACKET_2026-10-05.md',R/'homecoord_bench/task_revision/small_validation_plan_v1.py',R/'homecoord_bench/tests/test_small_validation_plan_v1.py',R/'homecoord_bench/task_revision/small_validation_design_audit_20261005.py',R/'homecoord_bench/tests/test_small_validation_design_audit_20261005.py',*B.glob('*.json')]
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'config_evidence':evidence,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'tests':{'actual_run':17,'plan':9,'design_audit':8,'result':'OK','full_suite_rerun':False},'experiment_runs':0,'freeze_performed':False,'scope':'local F2 late one-factor sensitivity only'}
(O/'SMALL_VALIDATION_V1_DESIGN_AUDIT_20261005.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'checks':len(checks),'errors':out['errors'],'configurations':28,'slots':84,'pairs':72,'certificates':28},ensure_ascii=False))
