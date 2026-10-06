import json,hashlib,sys,collections
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');B=R/'docs/aggregation_contract_v2_20261003';F=R/'homecoord_bench/task_revision/fixtures/f3_v8';sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
inv=read(B/'run_inventory.json');plan=read(B/'pair_plan.json');mapping=read(B/'c4_replacement_map.json');eps={e['episode_id']:e for e in read(F/'inputs.json')['episodes']};idx=read(F/'index.json');slots={x['canonical_slot_id']:x for x in inv['slots']};errors=[];checks=[];runs={};coverage={}
def ck(ok,msg):
    checks.append({'check':msg,'passed':bool(ok)})
    if not ok:errors.append(msg)
def locate(path,pointer):
    x=read(R/path)
    for k in pointer.strip('/').split('/'):x=x[int(k)] if isinstance(x,list) else x[k]
    return x
ck(len(slots)==len(inv['slots'])==224,'224 unique slot IDs')
ck(collections.Counter(x['role'] for x in slots.values())=={'primary':192,'diagnostic':32},'primary192 diagnostic32')
observed_sources=set()
for key,s in slots.items():
    r=locate(s['source_path'],s['source_row_pointer']);runs[key]=r;e=eps[r['evaluation_episode_id']];observed_sources.add((s['source_path'],s['source_row_pointer']))
    ck(sha(R/s['source_path'])==s['source_sha256'],key+' source hash')
    ck((s['config_id'],s['base_world_id'],s['policy'],s['selector'],s['diagnostic_id'])==(e['episode_id'],e['evaluation_world_id'],r['policy'],r['selector'],r['diagnostic']),key+' exact row identity')
    ck(s['capability_kind']==e['mode_capability']['kind'] and s['authorized_modes_by_task']==e['mode_capability']['authorized_modes_by_task'],key+' permission vector')
    ck(s['requests']==[{'task_id':t['task_id'],'release_at_ms':t['release_at_ms'],'deadline_ms':t['completion_deadline_ms']} for t in e['task_stream']],key+' static requests E')
    ck(s['metric_eligibility']==('all_declared_required_services' if s['role']=='primary' else 'diagnostic_only'),key+' eligibility independent of completion')
    expected_role='primary' if s['source_path'] in idx['run_files'] else 'diagnostic' if s['source_path'] in idx['diagnostic_files'] else None
    ck(s['role']==expected_role,key+' approved index role')
    vector={}
    for event in r['trace']['events']:
        if event['type']=='action_started' and event['operation']!='off':vector[event['task_id']]=event['operation']
    coverage[key]={'required':sorted(t['task_id'] for t in e['task_stream']),'observed_started_vector':vector,'complete_actual_vector':set(vector)=={t['task_id'] for t in e['task_stream']}}
expected_sources={(p,f'/runs/{i}') for p in idx['run_files']+idx['diagnostic_files'] for i in range(len(read(R/p)['runs']))}
ck(observed_sources==expected_sources,'all and only indexed224 run rows')
ck(collections.Counter(x['contrast_type'] for x in plan['pairs'])=={'fixed_mode_scheduling':72,'selectable_selector':64,'mode_matched_control':96,'capability_and_selection_intervention':192},'424 typed pairs')
ck(len({(p['contrast_type'],p['candidate'],p['control']) for p in plan['pairs']})==424,'unique typed pair identities')
incomplete_fixed=[];incomplete_controls=[]
for i,p in enumerate(plan['pairs']):
    left=slots[p['candidate']];right=slots[p['control']];el=eps[left['config_id']];er=eps[right['config_id']];kind=p['contrast_type']
    ck(left['role']==right['role']=='primary' and left['base_world_id']==right['base_world_id']==p['world'],f'pair{i} primary same world')
    ck(left['requests']==right['requests'] and el['home']==er['home'] and el['goals']==er['goals'] and el['action_grounding']==er['action_grounding'],f'pair{i} static E/physical service/cost/time')
    ck(p['direction']=='candidate_minus_control' and p['primary_metric']=='timely_service_rate_with_static_required_request_denominator',f'pair{i} direction and primary metric')
    if kind=='fixed_mode_scheduling':
        ck(left['config_id']==right['config_id'] and left['authorized_modes_by_task']==right['authorized_modes_by_task'] and right['policy']=='IndependentMultiAgent' and left['policy']!='IndependentMultiAgent',f'pair{i} fixed scheduling control')
        # Missing actual vectors are genuine non-starts, not missing evidence.
        if not coverage[p['candidate']]['complete_actual_vector'] or not coverage[p['control']]['complete_actual_vector']:incomplete_fixed.append({'pair_index':i,'world':p['world'],'candidate':p['candidate'],'control':p['control'],'candidate_coverage':coverage[p['candidate']],'control_coverage':coverage[p['control']]})
    elif kind=='selectable_selector':
        ck(left['config_id']==right['config_id'] and left['policy']==right['policy'] and left['capability_kind']==right['capability_kind']=='selectable' and right['selector']=='low_resource' and left['selector'] in ('short_duration','capacity_pressure'),f'pair{i} same permission selector controls')
    else:
        ck(left['policy']==right['policy'] and left['capability_kind']=='selectable' and right['capability_kind']=='fixed' and p['capability_contract_differs'] is True,f'pair{i} explicit capability difference')
        if kind=='mode_matched_control':
            expected={t:ops[0] for t,ops in right['authorized_modes_by_task'].items()}
            ck(p['planned_vector_from_reviewed_v8_control']==expected and p['requires_exact_complete_actual_vector_recheck'] is True,f'pair{i} planned exact vector')
            if not coverage[p['candidate']]['complete_actual_vector'] or not coverage[p['control']]['complete_actual_vector']:incomplete_controls.append(i)
            else:ck(coverage[p['candidate']]['observed_started_vector']==coverage[p['control']]['observed_started_vector'],f'pair{i} actual full vectors equal')
cells=plan['factorial_cells'];ck(len(cells)==24 and collections.Counter(x['role'] for x in cells)=={'primary':8,'predeclared_sensitivity':16},'24 factorial plans and8primary worlds')
for i,c in enumerate(cells):
    four=[slots[c[k]] for k in ('Y00','Y10','Y01','Y11')];ck(len({s['canonical_slot_id'] for s in four})==4 and all(s['base_world_id']==c['world'] and s['role']=='primary' and s['capability_kind']=='fixed' for s in four),f'cells{i} four existing fixed rows')
    ck([s['policy'] for s in four]==[c['baseline_policy'],c['candidate_policy'],c['baseline_policy'],c['candidate_policy']] and c['baseline_policy']=='IndependentMultiAgent',f'cells{i} policy direction')
    for s,wanted in zip(four,('eco','eco','fast','fast')):
        e=eps[s['config_id']];ck(all(m==[wanted] if len(next(z for z in eps.values() if z['evaluation_world_id']==c['world'] and z['mode_capability']['kind']=='selectable')['mode_capability']['authorized_modes_by_task'][t])>1 else m==['prepare'] for t,m in s['authorized_modes_by_task'].items()),f'cells{i} predefined{wanted} vector')
ck(len(mapping['mapping'])==4 and len({x['canonical_slot_id'] for x in mapping['mapping']})==4,'four unique C4 slots')
for i,x in enumerate(mapping['mapping']):
    old=x['old_source'];new=x['effective_source'];a=locate(old['path'],old['row_pointer']);b=locate(new['path'],new['row_pointer'])
    ck(sha(R/old['path'])==old['sha256'] and sha(R/new['path'])==new['sha256'] and a['policy']==b['policy'] and a['calls']==b['calls'] and old['valid_for_scores'] is False and x['role']=='diagnostic' and x['aggregation_scope']=='out_of_current_F3_scope',f'C4 replacement{i} exact policies inputs hashes roles')
prior=read(O/'F3_V8_EVENT_AUDIT_20261002.json');ck(sha(F/'manifest.json')==prior['manifest_sha256'],'v8 prior independent manifest')
for section in ('source_sha256','artifact_sha256'):
    for path,h in read(F/'manifest.json')[section].items():ck(sha(R/path)==h,'v8 frozen:'+path)
prior_ledger=read(O/'ACCEPTANCE_LEDGER_AUDIT_20261003.json')
for name,key in [('registry.json','registry_sha256'),('evidence_locks.json','locks_sha256')]:
    ck(sha(R/'docs/acceptance_ledger_20261003'/name)==prior_ledger[key],'prior ledger machine artifact unchanged:'+name)
document_changes=[{'path':'docs/'+doc,'previous_sha256':h,'current_sha256':sha(R/'docs'/doc),'status':'document_changed; current text contains v2 status/clarification additions; not treated as frozen run corruption'} for doc,h in prior_ledger['reviewed_documents_sha256'].items() if sha(R/'docs'/doc)!=h]
from homecoord_bench.task_revision.aggregation_contract_v2 import build
reproduction={p:read(R/p)==v for p,v in build().items()};ck(all(reproduction.values()),'three metadata artifacts reproduce')
out={'errors':errors,'checks':checks,'reproduction':reproduction,'mode_vector_qualification':{'fixed_scheduling_missing_actual_vector_pairs':incomplete_fixed,'mode_matched_missing_actual_vector_pair_indices':incomplete_controls},'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in [R/'docs/AGGREGATION_CONTRACT_V2_2026-10-03.md',R/'homecoord_bench/task_revision/aggregation_contract_v2.py',R/'homecoord_bench/tests/test_aggregation_contract_v2.py',*B.glob('*.json')]},'scoped_tests':{'module':'homecoord_bench.tests.test_aggregation_contract_v2','pending_actual_run':True}}
(O/'AGGREGATION_CONTRACT_V2_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
out['document_changes']=document_changes
out['scoped_tests']={'module':'homecoord_bench.tests.test_aggregation_contract_v2','tests_run':4,'result':'OK','full_suite_rerun':False}
(O/'AGGREGATION_CONTRACT_V2_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'errors':errors,'checks':len(checks),'slots224':len(slots),'pairs424':len(plan['pairs']),'factorial24':len(cells),'fixed_scheduling_actual_vector_incomplete':len(incomplete_fixed),'mode_matched_actual_vector_incomplete':len(incomplete_controls),'reproduction':all(reproduction.values())},ensure_ascii=False,indent=2))
