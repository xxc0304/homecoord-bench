import json, hashlib, sys, math
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs')
sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,msg):checks.append({'check':msg,'passed':bool(v)})
def same(a,b):
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(same(v,b[k]) for k,v in a.items())
    if isinstance(a,list):return isinstance(b,list) and len(a)==len(b) and all(same(v,w) for v,w in zip(a,b))
    if type(a) in (float,int) and type(b) in (float,int):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
    return a==b
def field(v,status='ok',**kw):return {'value':v,'status':status,**kw}
contract=R/'docs/aggregation_contract_v2_20261003'; freeze=read(contract/'freeze_20261004.json')
prior=read(O/'AGGREGATION_V2_CORRECTION_AUDIT_20261003.json')
ck(freeze['review_audit_sha256']==sha(O/'AGGREGATION_V2_CORRECTION_AUDIT_20261003.json'),'freeze references actual independent audit')
ck({p.replace('\\','/'):h for p,h in prior['reviewed_sha256'].items()}==freeze['sha256'],'freeze exactly prior seven reviewed hashes')
for p,h in freeze['sha256'].items():ck(sha(R/p)==h,'frozen contract '+p)
# Execute definitions of the previously independent replay, without its main loops or output writes.
src=Path('work/audit_f3_v8.py').read_text(encoding='utf-8'); ns={}
exec(compile(src[:src.index("for file in idx['run_files']:")],'independent_f3_replay_definitions','exec'),ns)
ck(not ns['hash_errors'],'F3 frozen hashes')
ck(sha(ns['B']/'manifest.json')==read(O/'F3_V8_EVENT_AUDIT_20261002.json')['manifest_sha256'],'F3 manifest equals previous independent lock')
saved_dir=R/'docs/f3_aggregation_v1_20261004'
worlds=[read(p) for p in sorted(saved_dir.glob('D-*.json'))]
saved_runs={}; saved_pairs=[]; saved_factors=[]
for w in worlds:
    for k,v in w['runs'].items():ck(k not in saved_runs,'unique saved run '+k);saved_runs[k]=v
    saved_pairs+=w['pairs'];saved_factors+=w['factorial']
inventory=read(contract/'run_inventory.json')['slots']; plan=read(contract/'pair_plan.json')
ck(len(worlds)==8 and len(saved_runs)==224 and len(saved_pairs)==424 and len(saved_factors)==24,'eight world files224runs424pairs24cells')
expected={}; evidence=[]
for s in inventory:
    key=s['canonical_slot_id']; ri=int(s['source_row_pointer'].split('/')[-1]); run=read(R/s['source_path'])['runs'][ri];e=ns['eps'][s['config_id']]
    d=ns['extended'](e,run,s['source_path'],ri,'main' if s['role']=='primary' else 'diagnostic')
    ck(not d['errors'],key+' independent state/permissions/proposals/receipts replay')
    m=d['computed']; ext=d['extended_metrics']; starts={};done={};ints=[]
    for it in d['intervals']:
        ints.append({'task_id':it['task_id'],'operation':it['operation'],'start_event_index':it['start_event'],'end_event_index':it['end_event'],'start_ms':it['start_ms'],'end_ms':it['end_ms'],'units':it['units']})
        if it['operation']!='off':
            starts[it['task_id']]={'at_ms':it['start_ms'],'event_index':it['start_event']}
            done[it['task_id']]={'at_ms':it['end_ms'],'event_index':it['end_event']}
    ids=[t['task_id'] for t in e['task_stream']]; n=len(ids);c=sum(m['task_correct_action_completed'].values());t=sum(m['task_deadline_met'].values());s_count=sum(m['task_correct_action_started'].values())
    cover={'required':n,'started':s_count,'completed':c,'on_time':t}
    rates={name:field(num/den if den else None,'ok' if den else ('no_eligible_requests' if not n else 'no_completed_requests'),required=n,completed=c,on_time=t,started=s_count) for name,num,den in [('service_completion_rate',c,n),('timely_service_rate',t,n),('timely_among_completed',t,c)]}
    tasks={}
    for tid in ids:
        cov={'required':1,'started':int(m['task_correct_action_started'][tid]),'completed':int(m['task_correct_action_completed'][tid])}
        tasks[tid]={k:field(m[mk][tid],'ok' if m[mk][tid] is not None else null_status,**cov) for k,mk,null_status in [('wait_ms','task_start_wait_ms','not_started'),('latency_ms','task_completion_latency_ms','not_completed'),('tardiness_ms','task_completion_tardiness_ms','not_completed')]}
    expected[key]={'identity':s,'required_ids':ids,'started':starts,'completed':done,'on_time_ids':sorted(tid for tid in ids if m['task_deadline_met'][tid]),'coverage':cover,'rates':rates,'tasks':tasks,'actual_modes':{tid:op for tid,op in ext['realized_mode_by_task'].items() if op is not None},'resource_intervals':ints,'cost':field(ext['total_executed_resource_time_units_ms'],**cover),'all_service_completion_ms':field(ext['all_service_completion_ms'],'ok' if c==n else 'not_completed',**cover)}
    ck(same(expected[key],saved_runs[key]),key+' saved complete run metrics agree with independent replay')
    evidence.append({'slot':key,'source':s['source_path'],'row':ri,'verdict':'符合设计' if not d['errors'] and same(expected[key],saved_runs[key]) else '须修正','release_event_indices':d['release_event_indices'],'service_start_completion_event_indices':{tid:{'start':starts.get(tid),'completion':done.get(tid)} for tid in ids},'peak_units':d['peak_units'],'capacity':d['capacity']})
def sub(a,b,status):return field(a['value']-b['value']) if a['value'] is not None and b['value'] is not None else field(None,status)
pair_lookup={p['pair_index']:p for p in saved_pairs}; exp_pairs=[]
for i,p in enumerate(plan['pairs']):
    a,b=expected[p['candidate']],expected[p['control']]
    qualified=True
    if p['contrast_type']=='mode_matched_control':
        qualified=set(a['actual_modes'])==set(a['required_ids']) and set(b['actual_modes'])==set(b['required_ids'])
        if qualified:ck(a['actual_modes']==b['actual_modes'],f'pair{i} exact actual vector')
    status='ok' if qualified else 'incomplete_actual_vector'
    both_complete=all(r['coverage']['completed']==r['coverage']['required'] for r in (a,b))
    q={'pair_index':i,'contrast_type':p['contrast_type'],'candidate':p['candidate'],'control':p['control'],'world':p['world'],'qualification':status,'candidate_coverage':a['coverage'],'control_coverage':b['coverage'],'rate_deltas':{k:sub(a['rates'][k],b['rates'][k],'no_completed_requests') for k in a['rates']},'all_service_completion_delta':sub(a['all_service_completion_ms'],b['all_service_completion_ms'],'not_completed'),'observed_cost_delta':sub(a['cost'],b['cost'],'evidence_error'),'matched_service_cost_saving':field(b['cost']['value']-a['cost']['value']) if both_complete else field(None,'unequal_service_coverage'),'directions':{'default':'candidate_minus_control','matched_service_cost_saving':'control_minus_candidate'},'task_deltas':{tid:{k:sub(a['tasks'][tid][k],b['tasks'][tid][k],'not_started' if k=='wait_ms' else 'not_completed') for k in a['tasks'][tid]} for tid in a['required_ids']}}
    if not qualified:
        q['rate_deltas']={k:field(None,status) for k in q['rate_deltas']}
        for k in ('all_service_completion_delta','observed_cost_delta','matched_service_cost_saving'):q[k]=field(None,status)
        q['task_deltas']={tid:{k:field(None,status) for k in v} for tid,v in q['task_deltas'].items()}
    ck(same(q,pair_lookup[i]),f'pair{i} independent all metrics/status/direction')
    exp_pairs.append(q)
factor_lookup={(f['plan']['world'],f['plan']['candidate_policy']):f for f in saved_factors}; exp_factors=[]
for f in plan['factorial_cells']:
    cells={k:expected[f[k]] for k in ('Y00','Y10','Y01','Y11')};fields={};decomp={}
    for metric in ('timely_service_rate','service_completion_rate','all_service_completion_ms','cost'):
        fields[metric]={k:r['rates'][metric] if metric in r['rates'] else r[metric] for k,r in cells.items()}
        vals=[v['value'] for v in fields[metric].values()]
        if any(v is None for v in vals):decomp[metric]={k:field(None,'not_completed') for k in ('S','M','I','T')}
        else:
            a,b,c,d=vals;decomp[metric]={k:field(v) for k,v in zip(('S','M','I','T'),(b-a,c-a,d-b-c+a,d-a))}
            ck(math.isclose(decomp[metric]['T']['value'],sum(decomp[metric][k]['value'] for k in ('S','M','I')),abs_tol=1e-9),f'{f["world"]}/{f["candidate_policy"]}/{metric} decomposition identity')
    row={'plan':f,'cells':fields,'decomposition':decomp,'cost_interpretation':'observed_cost_algebra_not_savings'}
    ck(same(row,factor_lookup[(f['world'],f['candidate_policy'])]),f'{f["world"]}/{f["candidate_policy"]} fourcell independent all fields')
    exp_factors.append(row)
summary=read(saved_dir/'summary.json'); primary=[f for f in exp_factors if f['plan']['role']=='primary']
for metric in ('timely_service_rate','service_completion_rate','all_service_completion_ms','cost'):
    for k in ('S','M','I','T'):
        vals=[f['decomposition'][metric][k]['value'] for f in primary];n=sum(v is not None for v in vals)
        want=field(sum(vals)/8 if n==8 else None,'ok' if n==8 else 'not_completed',valid_worlds=n,required_worlds=8,weight_per_world=1/8)
        ck(same(want,summary['equal_world_factorial_summary'][metric][k]),f'summary {metric}/{k} fixed8weight null coverage')
for cell in ('Y00','Y10','Y01','Y11'):
    rows=[expected[f['plan'][cell]] for f in primary];den=sum(r['coverage']['required'] for r in rows)
    for metric,count in [('service_completion_rate','completed'),('timely_service_rate','on_time')]:
        num=sum(r['coverage'][count] for r in rows);vals=[r['rates'][metric]['value'] for r in rows]
        want={'pooled_request_rate':field(num/den,numerator=num,denominator=den),'equal_world_mean_rate':field(sum(vals)/8,required_worlds=8,weight_per_world=1/8)}
        ck(same(want,summary['predefined_primary_four_cell_rate_summary'][cell][metric]),f'summary {cell}/{metric} pooled vs equalworld')
ck(len([p for p in exp_pairs if p['contrast_type']=='fixed_mode_scheduling' and any(p[k]['started']<p[k]['required'] for k in ('candidate_coverage','control_coverage'))])==36,'36 fixed failures retained')
ck(sum(p['qualification']=='incomplete_actual_vector' for p in exp_pairs)==12,'12 incomplete actual vector controls null')
ck(sum(s['role']=='diagnostic' for s in inventory)==32 and all(s['role']=='primary' for p in plan['pairs'] for s in [next(x for x in inventory if x['canonical_slot_id']==p['candidate']),next(x for x in inventory if x['canonical_slot_id']==p['control'])]),'diagnostic32 excluded from all primary pairs')
ck(all(r['rates']['timely_among_completed']['value'] is None and r['rates']['timely_among_completed']['status']=='no_completed_requests' for r in expected.values() if r['identity']['diagnostic_id'] in ('off','noop')),'off/noop conditional rates null')
from homecoord_bench.task_revision.f3_aggregation_v1 import artifacts
ck(all(same(v,read(R/p)) for p,v in artifacts().items()),'all nine saved artifacts reproduce')
files=[R/'homecoord_bench/task_revision/f3_aggregation_v1.py',R/'homecoord_bench/tests/test_f3_aggregation_v1.py',R/'docs/F3_AGGREGATION_V1_REVIEW_PACKET_2026-10-04.md',contract/'freeze_20261004.json',*saved_dir.glob('*.json')]
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'run_evidence':evidence,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'specialist_tests':{'tests_run':21,'result':'OK','full_suite_rerun':False},'scope':'F3 v8 fixed frozen traces only','rankings_created':False}
(O/'F3_AGGREGATION_V1_AUDIT_20261004.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'checks':len(checks),'errors':out['errors'],'runs':len(expected),'pairs':len(exp_pairs),'factorials':len(exp_factors)},ensure_ascii=False))
