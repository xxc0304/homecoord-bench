import copy, hashlib, json, sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.')
sys.path.insert(0,str(R))
O=Path('outputs'); B=R/'docs/aggregation_contract_v2_20261003'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
prior=read(O/'AGGREGATION_CONTRACT_V2_AUDIT_20261003.json')
checks=[]
def ck(v,label): checks.append({'check':label,'passed':bool(v)})
for rel,h in prior['reviewed_sha256'].items():
    if rel.endswith(('run_inventory.json','c4_replacement_map.json')): ck(sha(R/rel)==h,'unchanged '+rel)
ledger=read(O/'ACCEPTANCE_LEDGER_AUDIT_20261003.json')
for name,key in [('registry.json','registry_sha256'),('evidence_locks.json','locks_sha256')]:
    ck(sha(R/'docs/acceptance_ledger_20261003'/name)==ledger[key],'unchanged ledger '+name)
F=R/'homecoord_bench/task_revision/fixtures/f3_v8'
ck(sha(F/'manifest.json')==read(O/'F3_V8_EVENT_AUDIT_20261002.json')['manifest_sha256'],'unchanged frozen manifest')
for section in ('source_sha256','artifact_sha256'):
    for p,h in read(F/'manifest.json')[section].items(): ck(sha(R/p)==h,'frozen hash '+p)
inv=read(B/'run_inventory.json'); slots={s['canonical_slot_id']:s for s in inv['slots']}
plan=read(B/'pair_plan.json'); fixed=[]; mechanism=[]; coverage={}
for key,s in slots.items():
    ck(sha(R/s['source_path'])==s['source_sha256'],key+' source hash')
    r=read(R/s['source_path'])['runs'][int(s['source_row_pointer'].split('/')[-1])]
    starts=[e for e in r['trace']['events'] if e['type']=='action_started' and e['operation']!='off']
    modes={e['task_id']:e['operation'] for e in starts}
    coverage[key]=set(modes)==set(s['authorized_modes_by_task'])
    if s['capability_kind']=='fixed':
        ck(all(len(v)==1 for v in s['authorized_modes_by_task'].values()),key+' unique fixed authorization')
        for e in starts: ck(e['operation'] in s['authorized_modes_by_task'][e['task_id']],key+' started action authorized '+e['task_id'])
for i,p in enumerate(plan['pairs']):
    if p['contrast_type']=='fixed_mode_scheduling':
        fixed.append(i); a=slots[p['candidate']]; b=slots[p['control']]
        ck(a['requests']==b['requests'] and a['authorized_modes_by_task']==b['authorized_modes_by_task'],f'fixed{i} static E and authorization')
        ck(p['primary_pair_qualification']=={'requires_complete_actual_vector':False,'retain_not_started_requests_and_pairs':True,'match_on':'unique_predeclared_authorized_vector','validate_all_started_actions_against_authorization':True},f'fixed{i} qualification')
        ck('complete_actual_mode_vector' not in p['fixed_fields'],f'fixed{i} no complete-vector gate')
    if p['contrast_type']=='mode_matched_control':
        mechanism.append(i)
        ck('complete_actual_mode_vector' in p['fixed_fields'] and p['requires_exact_complete_actual_vector_recheck'],f'mechanism{i} still requires actual vector')
missing_fixed=[i for i in fixed if not coverage[plan['pairs'][i]['candidate']] or not coverage[plan['pairs'][i]['control']]]
missing_mechanism=[i for i in mechanism if not coverage[plan['pairs'][i]['candidate']] or not coverage[plan['pairs'][i]['control']]]
ck(len(fixed)==72 and len(missing_fixed)==36,'72 fixed pairs retain36 incomplete-start pairs')
ck(missing_mechanism==prior['mode_vector_qualification']['mode_matched_missing_actual_vector_pair_indices'],'96 mechanism plans retain same12 incomplete-vector pairs')
# Undo only submitted metadata edits, to verify the remaining plan is byte-equivalent.
old=copy.deepcopy(plan)
old.pop('rate_boundary_rule');old.pop('qualification_is_per_metric')
for p in old['pairs']:
    if p['contrast_type']=='fixed_mode_scheduling':
        p.pop('primary_pair_qualification')
        p['fixed_fields']=p['fixed_fields'][:-2]+['fixed_authorization','complete_actual_mode_vector']
old_hash=hashlib.sha256((json.dumps(old,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest()
ck(old_hash==prior['reviewed_sha256']['docs\\aggregation_contract_v2_20261003\\pair_plan.json'],'only declared qualification/boundary metadata edits; pair identities cells other fields unchanged')
from homecoord_bench.task_revision.aggregation_contract_v2 import build,service_rate_boundary
ck(all(read(R/p)==v for p,v in build().items()),'three artifacts reproduce')
# Count-only exhaustive boundary verification; does not read completion outcomes or compute run scores.
for n in range(9):
    for c in range(n+1):
        for t in range(c+1):
            got=service_rate_boundary(n,c,t)
            for name,den,num in [('service_completion_rate',n,c),('timely_service_rate',n,t),('timely_among_completed',c,t)]:
                status='no_eligible_requests' if not n else 'no_completed_requests' if not den else 'ok'
                ck(got[name]=={'value':num/den if den else None,'status':status,'required':n,'completed':c,'on_time':t},f'count reference {n}/{c}/{t} {name}')
for triple in [(1,True,0),(True,0,0),(1,0,False),(2,-1,0),(2,1,-1),(2,3,0),(2,1,2),(2,1.0,0)]:
    try: service_rate_boundary(*triple); ok=False
    except ValueError: ok=True
    ck(ok,'invalid counts rejected '+str(triple))
files=[R/'docs/AGGREGATION_CONTRACT_V2_2026-10-03.md',R/'docs/AGGREGATION_CONTRACT_V2_CORRECTION_2026-10-03.md',R/'homecoord_bench/task_revision/aggregation_contract_v2.py',R/'homecoord_bench/tests/test_aggregation_contract_v2.py',*B.glob('*.json')]
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'fixed_pairs':len(fixed),'incomplete_fixed_pairs_retained':missing_fixed,'incomplete_mechanism_pairs':missing_mechanism,'scoped_tests':{'tests_run':9,'result':'OK','full_suite_rerun':False},'actual_run_metrics_computed':False,'adapter_reviewed':False}
(O/'AGGREGATION_V2_CORRECTION_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'errors':out['errors'],'checks':len(checks),'fixed_pairs':len(fixed),'incomplete_fixed_retained':len(missing_fixed),'incomplete_mechanism':len(missing_mechanism)},ensure_ascii=False))
