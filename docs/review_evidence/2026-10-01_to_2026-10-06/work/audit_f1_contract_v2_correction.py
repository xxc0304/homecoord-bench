import json,hashlib,sys,itertools,copy
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs');sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,s):checks.append({'check':s,'passed':bool(v)})
author=read(R/'docs/f1_statistical_contract_v2_20261004/author_verification.json')
for p,h in author['preserved_sha256'].items():ck(sha(R/p)==h,'author-declared preserved file '+p)
ck(len(author['preserved_sha256'])==109,'109 declared preservation locks')
# Use prior independently retained F3 hashes where available, not only the author list.
for f in ['AGGREGATION_V2_CORRECTION_AUDIT_20261003.json','F3_AGGREGATION_V1_AUDIT_20261004.json']:
    for p,h in read(O/f)['reviewed_sha256'].items():ck(sha(R/p)==h,'prior independent lock '+p)
v1=read(R/'docs/f1_statistical_contract_v1_20261004/plan.json');v2=read(R/'docs/f1_statistical_contract_v2_20261004/plan.json')
ck(sha(R/'docs/f1_statistical_contract_v1_20261004/plan.json')=='d8fb7fc57aacc70caa441ffda66884d6ffa143e9390574d3aa51c17892809430','v1 plan equals prior review hash')
ck(sha(R/'docs/F1_STATISTICAL_CONTRACT_V1_2026-10-04.md')=='23f302299922c3766bed9096f71680b2f80f91f82d408fdb21affffcf4841fb1','v1 contract equals prior review hash')
back=copy.deepcopy(v2)
for k in ('metric_rules','supersedes'):back.pop(k)
back['version']=v1['version']
for cell in back['four_cells']:cell.pop('metric_rules_ref');cell.pop('population_ref')
ck(back==v1,'whole v1 object unchanged except submitted rules version references')
ck(len(v2['runs'])==72 and len(v2['pairs'])==168 and len(v2['four_cells'])==18,'72runs168pairs18fourcells')
rules=v2['metric_rules']
ck(rules['four_cell_allowlist']=={'fixed_E_rates':['service_rate','timely_service_rate'],'run_event_or_process':['executed_capacity_violation_duration_ms','excess_resource_unit_ms','coordination_accept_count','coordination_defer_count','coordination_reject_count','action_rejected_count','retry_queued_count','retry_scheduled_count','reservation_count','actual_start_count'],'same_four_cell_completed_population':['task_start_wait_ms','execution_ms','completion_latency_ms','tardiness_ms'],'all_E_completed_in_all_four_cells':['whole_house_completion_ms']},'exact explicit metric allowlist')
ck(rules['unlisted_metrics']=='not_eligible_for_four_cell_interaction_in_this_version','unlisted metrics prohibited')
ck(rules['template_macro']=={'metrics':['service_rate','timely_service_rate'],'slots_per_template_per_policy':12,'weight_each_slot':'1/12','weight_each_template':'1/2','skip_null_or_missing_slots':False},'fixedE main rates only macro12slots2templates no renormalization')
ck(not rules['conditional_timely_rate']['four_cell_interaction'] and not rules['conditional_timely_rate']['template_macro_aggregation'] and not rules['completed_only_means_on_each_cells_own_C']['four_cell_interaction'],'conditional indicators not used in interactions')
ck(rules['cohort']['missing_metric_on_K']=='data_error_not_drop_task_not_zero' and rules['cohort']['missing_source_or_cell']=='data_error_keep_expected_slot_not_score_as_normal_failure','missing metric source and cell data-error rules')
from homecoord_bench.task_revision.f1_statistical_contract_v2 import analysis_population,bundle
ck(bundle()==v2,'saved metadata reproduces')
CELL=('tight_base','tight_loose','adequate_base','adequate_loose')
# All 4096 completion patterns on three synthetic tasks; no source outcome access.
E=['c','a','b'];subs=[[t for i,t in enumerate(E) if mask & (1<<i)] for mask in range(8)]
patterns=0
for sets in itertools.product(subs,repeat=4):
    by=dict(zip(CELL,sets));got=analysis_population(E,by)
    K=[t for t in E if all(t in by[c] for c in CELL)]
    want={'required_task_ids':E,'completed_task_ids_by_cell':by,'common_task_ids':K,'common_count':len(K),'required_count':3,'coverage':len(K)/3,'excluded_tasks':[{'task_id':t,'reason':'not_completed_in_all_four_cells','not_completed_cells':[c for c in CELL if t not in by[c]]} for t in E if t not in K],'eligible':bool(K),'null_reason':None if K else 'no_common_completed_requests','all_E_completed_in_all_four_cells':all(set(s)==set(E) for s in sets)}
    ck(got==want,'synthetic fourcell set pattern '+str(patterns));patterns+=1
counter=analysis_population(['a','b'],dict(zip(CELL,[['a'],['a','b'],['a','b'],['a','b']])))
K=counter['common_task_ids'];times={'a':100,'b':1000}
y=[sum(times[t] for t in K)/len(K) for _ in CELL]
ck((y[3]-y[1])-(y[2]-y[0])==0 and counter['required_count']==2 and counter['coverage']==0.5,'composition counterexample resolved with unchanged E')
for E0,C0 in [(['a'],{}),(['a'],{**{c:[] for c in CELL},'extra':[]}),(['a','a'],{c:[] for c in CELL}),(['a'],dict(zip(CELL,[['a','a'],[],[],[]]))),(['a'],dict(zip(CELL,[[],[],[],['x']]))),([],{c:[] for c in CELL})]:
    try:analysis_population(E0,C0);ok=False
    except ValueError:ok=True
    ck(ok,'missing extra duplicate unknown empty input rejected '+str(E0)+str(C0))
files=[R/'docs/F1_STATISTICAL_CONTRACT_V1_2026-10-04.md',R/'docs/F1_STATISTICAL_CONTRACT_V2_CORRECTION_2026-10-04.md',R/'docs/F1_STATISTICAL_CONTRACT_V2_TARGETED_REVIEW_PACKET_2026-10-04.md',R/'homecoord_bench/task_revision/f1_statistical_contract_v2.py',R/'homecoord_bench/tests/test_f1_statistical_contract_v2.py',R/'docs/f1_statistical_contract_v1_20261004/plan.json',R/'docs/f1_statistical_contract_v2_20261004/plan.json',R/'docs/f1_statistical_contract_v2_20261004/author_verification.json']
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'synthetic_set_patterns':patterns,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'tests':{'actual_run':17,'new_v2':9,'v1':8,'result':'OK','author43not_represented_as_reviewer43':True,'full_suite_rerun':False},'scope':'K E metric eligibility correction and metadata only','actual_strategy_scores_computed':False,'adapter_reviewed':False,'freeze_performed':False}
(O/'F1_CONTRACT_V2_CORRECTION_AUDIT_20261004.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'errors':out['errors'],'checks':len(checks),'synthetic_patterns':patterns,'author_declared_hashes_checked':len(author['preserved_sha256'])},ensure_ascii=False))
