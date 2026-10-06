import json,hashlib,itertools
from pathlib import Path
R=Path('.');B=R/'homecoord_bench/task_revision/fixtures/f2_v7';O=Path('outputs')
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=read(B/'manifest.json')
assert sha(B/'manifest.json')==read(O/'F2_V7_EVENT_AUDIT_20261002.json')['manifest_sha256'] if 'manifest_sha256' in read(O/'F2_V7_EVENT_AUDIT_20261002.json') else True
for section in ('source_sha256','artifact_sha256'):
    for p,h in manifest[section].items():assert sha(R/p)==h,p
episodes={e['episode_id']:e for e in read(B/'inputs.json')['episodes']};idx=read(B/'index.json')
P=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')
runs=[]; lookup={}
for p in idx['run_files']:
    eid=Path(p).stem;e=episodes[eid]
    for i,policy in enumerate(P):
        sid='F2|v7|'+eid+'|'+policy
        r={'slot_id':sid,'episode_id':eid,'policy':policy,'role':'primary','source_path':p,'source_pointer':f'/runs/{i}','source_sha256':sha(R/p),'required_requests':[{'task_id':t['task_id'],'release_ms':t['release_at_ms'],'deadline_ms':t['completion_deadline_ms']} for t in e['task_stream']]}
        runs.append(r);lookup[(eid,policy)]=sid
pairs=[];groups=[]
for e in episodes.values():
    for p in P[:-1]:pairs.append({'kind':'policy','left':lookup[(e['episode_id'],'GateRetryRule')],'right':lookup[(e['episode_id'],p)]})
for base in ('01','02'):
    eid=lambda cap,arrival:f'F2R1-D-F2-{base}-{cap}-{arrival}'
    for policy in P:
        for arrival in ('simultaneous','late'):pairs.append({'kind':'capacity','left':lookup[(eid('competition',arrival),policy)],'right':lookup[(eid('no_competition',arrival),policy)]})
        for cap in ('competition','no_competition'):pairs.append({'kind':'arrival','left':lookup[(eid(cap,'simultaneous'),policy)],'right':lookup[(eid(cap,'late'),policy)]})
        groups.append({'base':base,'policy':policy,'cell_order':['tight_simultaneous','tight_late','adequate_simultaneous','adequate_late'],'slots':[lookup[(eid(c,a),policy)] for c,a in [('competition','simultaneous'),('competition','late'),('no_competition','simultaneous'),('no_competition','late')]]})
diags=[{'source_path':p,'source_sha256':sha(R/p),'role':'counterfactual_prefix_validation_only','expected_run_rows':4} for p in idx['diagnostic_files']]
assert len(runs)==32 and len(pairs)==56 and len(groups)==8 and len(diags)==12
out={'status':'draft_scope_pending_statistical_contract_review_not_frozen','primary_runs':runs,'pairs':pairs,'four_cells':groups,'counterfactual_sources':diags,'counterfactual_expected_runs':48,'diagnostics_in_main_denominator':False,'direction':'right_minus_left','primary_candidate':'ConstraintCoordinator','baseline':'GateRetryRule','sensitivity_policies':['DeadlineAwareCoordinator','IndependentMultiAgent'],'scope_hashes':{str(p.relative_to(R)):sha(p) for p in [B/'manifest.json',B/'inputs.json',B/'index.json']},'scores_computed':False,'adapter_implemented':False,'api_calls':0,'new_simulator_runs':0,'metadata_pointer_basis':'prior accepted v7 index and fixed policy order; revalidate each row during adapter review'}
(O/'F2_STATISTICAL_SCOPE_DRAFT_20261004.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('F2 draft:32primary,56pairs,8fourcells,48counterfactual; no outcome metrics read')
