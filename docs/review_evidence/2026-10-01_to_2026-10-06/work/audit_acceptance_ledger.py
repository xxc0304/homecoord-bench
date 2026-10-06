import json,hashlib,sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');B=R/'docs/acceptance_ledger_20261003';sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
reg=read(B/'registry.json');locks=read(B/'evidence_locks.json');errors=[];checks=[]
def ck(ok,msg):
    checks.append({'check':msg,'passed':bool(ok)})
    if not ok:errors.append(msg)
expected={'C1':('v6',8,32,16),'C3-F1':('phase_b_legacy',8,72,0),'C3-F2':('v7',8,32,48),'C3-F3':('v8',32,192,32),'C4':('v9_valid_plus_v10_replacement',14,56,40),'dependency':('v11',13,52,0),'C2':('v12',24,24,8)}
ck(len(reg['groups'])==7 and set(g['family'] for g in reg['groups'])==set(expected),'seven review groups')
for g in reg['groups']:
    f=g['family'];ck((g['effective_version'],g['configuration_count'],g['reviewed_primary_runs'],g['diagnostic_or_counterfactual_runs'])==expected[f],f+' reviewed scope counts')
    ck(not g['independent_dual_review'] and not g['model_comparison_authorized'] and g['aggregation_acceptance'] is None,f+' scope not widened')
    ck(sha(Path(g['review_record']['absolute_path']))==g['review_record']['sha256'],f+' external reviewer report lock')
    ck(len([c for c in reg['configurations'] if c['family']==f])==g['configuration_count'],f+' catalogued primary configuration count')
    if f=='C4':ck(sha(Path(g['v9_design_and_partial_review']['absolute_path']))==g['v9_design_and_partial_review']['sha256'],'C4 v9 partial review lock')
ck(len({(c['family'],c['version'],c['episode_id']) for c in reg['configurations']})==len(reg['configurations']),'unique configuration identities')
ck(reg['aggregation_acceptance'] is None and not reg['performance_aggregation_computed'],'no aggregation falsely accepted')
for section in ('relative_artifact_sha256','source_sha256'):
    for p,h in locks[section].items():ck(sha(R/p)==h,section+':'+p)
for f,ref in locks['review_sources'].items():ck(sha(Path(ref['absolute_path']))==ref['sha256'],f+' external source double reference')
replace=reg['replacement'];old=read(R/replace['invalid_source'])['runs'];new=read(R/replace['replacement_source'])['runs'];mapping=[]
ck(len(old)==len(new)==4,'four C4 replacement rows')
for i,(x,y) in enumerate(zip(old,new)):
    ok=x['policy']==y['policy'] and x['calls']==y['calls'] and y['result']['task_completion_latency_ms']['bedroom_clean']==8100
    mapping.append({'old_run_index':i,'new_run_index':i,'policy':x['policy'],'identity_and_inputs_equal':ok});ck(ok,'C4 matching replacement '+str(i))
ck(replace['effective_original_cohort_runs']==96 and replace['do_not_add_targeted_28_as_new_samples'] is True,'C4 nominal 96 replacement cohort, no validation additions')
c={x['episode_id']:x for x in reg['configurations'] if x['family']=='dependency'}
ck(c['DEP11-INFEASIBLE_8000']['role']=='infeasible_pressure_excluded','8000 diagnostic excluded statically')
for name in ('CANCEL_NO_RESTORE','CANCEL_RESTORE','RESTART_NO_RESTORE','INVALID_PROPOSAL'):ck(c['DEP11-'+name]['role']=='lifecycle_or_invalid_proposal_diagnostic',name+' static diagnostic')
for name in ('FORGED_STATE','STALE_NATURAL_RACE'):ck(c['DEP11-'+name]['role']=='feasible_adversarial_correctness_control',name+' static correctness subset')
c1=read(R/'homecoord_bench/results/protection_v6_offline_20261002.json');ck({'action_template','required_action'}<=set(c1['runs'][0]['trace']['agent_requests'][0]['task']),'C1 actual scripted answer fields documented')
from homecoord_bench.task_revision.acceptance_ledger import build
reproduction={p:read(R/p)==v for p,v in build().items()};ck(all(reproduction.values()),'two ledger artifacts reproduce')
# Measure schema coverage; do not calculate scores or rankings.
coverage={'configuration_rows':len(reg['configurations']),'all_have_numeric_metric_eligible_mask':all(isinstance(x.get('metric_eligibility'),dict) for x in reg['configurations']),'has_run_level_replacement_rows':'replacement_rows' in reg,'has_canonical_metric_definitions':'metric_definitions' in reg,'has_full_diagnostic_run_inventory':'diagnostic_runs' in reg,'note':'Current registry is scope metadata, not a complete aggregation adapter contract.'}
docs=('ACCEPTANCE_LEDGER_2026-10-03.md','CROSS_FAMILY_AGGREGATION_DRAFT_2026-10-03.md','RESEARCH_QUESTIONS_NEXT_2026-10-03.md')
out={'errors':errors,'checks':checks,'registry_sha256':sha(B/'registry.json'),'locks_sha256':sha(B/'evidence_locks.json'),'reviewed_documents_sha256':{p:sha(R/'docs'/p) for p in docs},'replacement_checks':mapping,'schema_coverage':coverage,'reproduction':reproduction,'scoped_tests':{'module':'homecoord_bench.tests.test_acceptance_ledger','tests':5,'failures':0,'errors':0,'full505_not_run':True}}
(O/'ACCEPTANCE_LEDGER_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'errors':errors,'checks':len(checks),'config_rows':len(reg['configurations']),'replacement4':all(x['identity_and_inputs_equal'] for x in mapping),'schema_coverage':coverage},ensure_ascii=False,indent=2))
