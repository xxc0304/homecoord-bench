import json,hashlib,copy,sys,collections,math
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs');B=R/'docs/f2_aggregation_v1_20261004'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,s):checks.append({'check':s,'passed':bool(v)})
def eq(a,b):
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(eq(v,b[k]) for k,v in a.items())
    if isinstance(a,list):return isinstance(b,list) and len(a)==len(b) and all(eq(v,w) for v,w in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,abs_tol=1e-9,rel_tol=1e-12)
    return a==b
freeze=read(R/'docs/f2_statistical_contract_v1_20261004/freeze_20261004.json');prior=read(O/'F2_STATISTICAL_CONTRACT_V1_AUDIT_20261004.json')
ck(freeze['reviewed_sha256']=={p.replace('\\','/'):h for p,h in prior['reviewed_sha256'].items()},'freeze exact prior independent six hashes')
for name in ('review','review_audit'):ck(sha(Path(freeze[name+'_path']))==freeze[name+'_sha256'],'freeze '+name+' actual SHA')
for section in ('reviewed_sha256','source_sha256','runtime_source_sha256'):
    for p,h in freeze[section].items():ck(sha(R/p)==h,'frozen '+p)
author=read(B/'author_verification.json')
for p,h in author['protected_sha256'].items():ck(sha(R/p)==h,'protection '+p)
ck(len(author['protected_sha256'])==182,'182 protected entries')
# Definitions from the prior independent F2 review; no simulator or adapter imports.
src=Path('work/audit_f2_v7.py').read_text(encoding='utf-8');ns={}
exec(compile(src[:src.index('details=[]')],'prior_independent_f2_definitions','exec'),ns)
ck(not ns['hash_errors'],'old F2 source/artifact hashes')
plan=read(R/freeze['plan_path']);rules=plan['metric_rules'];tm=rules['time_allowlist'];expected={};raw={};evidence=[]
saved={r['slot_id']:r for p in B.glob('F2R1-*.json') for r in read(p)['runs']}
for item in plan['runs']:
    sid=item['slot_id'];ri=int(item['source_pointer'].split('/')[-1]);r=read(R/item['source_path'])['runs'][ri];ep=ns['eps'][item['episode_id']];ev=r['trace']['events'];tasks={t['task_id']:t for t in ep['task_stream']}
    d=ns['audit'](ep,r,item['source_path'],ri,'main');ck(not d['errors'],sid+' independently replayed complete input state permissions receipts')
    ck((r['evaluation_episode_id'],r['policy'])==(item['episode_id'],item['policy']),sid+' actual row identity')
    count=collections.Counter();affected=collections.defaultdict(set);reasons=collections.defaultdict(collections.Counter)
    rel={};ret={};starts={};done={}
    for i,e in enumerate(ev):
        k=e['type'];tid=e.get('task_id');count[k]+=1
        if tid is not None:affected[k].add(tid)
        if 'reason' in e:reasons[k][str(e['reason'])]+=1
        if k=='coordination_decision':count['coordination_'+e['decision']]+=1;affected['coordination_'+e['decision']].add(tid)
        if k=='task_released':rel[tid]=(i,e['timestamp_ms'])
        if k=='proposal_returned':ret[tid]=(i,e['timestamp_ms'])
        if k=='action_started' and e['operation']=='prepare':starts[tid]=(i,e['timestamp_ms'])
        if k=='action_completed' and e['operation']=='prepare':done[tid]=(i,e['timestamp_ms'])
    per={}
    for tid,t in tasks.items():
        ri0,R0=rel[tid];pi,P=ret[tid];si,S=starts.get(tid,(None,None));fi,F=done.get(tid,(None,None))
        per[tid]={'release_ms':R0,'deadline_ms':t['completion_deadline_ms'],'proposal_return_ms':P,'start_ms':S,'completion_ms':F,'started':S is not None,'completed':F is not None,'timely':F is not None and F<=t['completion_deadline_ms'],'logical_proposal_return_ms':P-R0,'proposal_to_start_ms':S-P if S is not None else None,'task_start_wait_ms':S-R0 if S is not None else None,'execution_ms':F-S if F is not None else None,'completion_latency_ms':F-R0 if F is not None else None,'tardiness_ms':max(0,F-t['completion_deadline_ms']) if F is not None else None,'event_indices':{'release':ri0,'return':pi,'start':si,'completion':fi},'null_reasons':{'start':None if S is not None else 'not_started','completion':None if F is not None else 'not_completed'},'coordination_compute_ms':None,'API_wallclock_ms':None,'unobserved_reason':'not_instrumented'}
    intervals=[{'task_id':it['task_id'],'proposal_id':ev[it['start_event']]['proposal_id'],'start_event_index':it['start_event'],'completion_event_index':it['end_event'],'start_ms':it['start_ms'],'end_ms':it['end_ms'],'units':it['units'],'operation':ev[it['start_event']]['operation']} for it in d['intervals']]
    cap=ep['home']['resources']['max_power_kw'];safety=[];last=0
    for i,e in enumerate(ev):
        now=e['timestamp_ms'];load=sum(it['units'] for it in intervals if it['start_ms']<=last<it['end_ms'])
        if now>last and load>cap:safety.append({'start_ms':last,'end_ms':now,'load_units':load,'capacity_units':cap,'next_event_index':i})
        last=now
    validity=[];state=copy.deepcopy(ep['initial_state']['values']);before={}
    for i,e in enumerate(ev):
        tid=e.get('task_id')
        if e['type']=='state_update':
            if e.get('source')=='action_started':before[tid]=copy.deepcopy(state)
            for p,v in e['patch'].items():ns['put'](state,p,v)
        elif e['type']=='action_started':
            prestate=before.pop(tid,state)
            validity.append({'task_id':tid,'event_index':i,'valid':all(ns['holds'](prestate,q) for q in e['requires'])})
        elif e['type']=='action_completed':
            for p,v in e['effects'].items():ns['put'](state,p,v)
    n=len(tasks);c=len(done);t=sum(p['timely'] for p in per.values());E=list(tasks);early=[t for t in E if t!='water'];L=per['water']['release_ms']
    metrics={'service_rate':c/n,'timely_service_rate':t/n,'executed_capacity_violation_duration_ms':sum(it['end_ms']-it['start_ms'] for it in safety),'excess_resource_unit_ms':sum((it['end_ms']-it['start_ms'])*(it['load_units']-cap) for it in safety),'whole_house_completion_ms':max(p['completion_ms'] for p in per.values())-ep['episode_release_at_ms'] if c==n else None,**{k:count[k.removesuffix('_count')] for k in ('coordination_defer_count','action_rejected_count','retry_queued_count','retry_scheduled_count')}}
    subsets={name:{'required_task_ids':ids,'denominators':{'required':len(ids),'completed':sum(per[t]['completed'] for t in ids),'timely':sum(per[t]['timely'] for t in ids)},'service_rate':sum(per[t]['completed'] for t in ids)/len(ids),'timely_service_rate':sum(per[t]['timely'] for t in ids)/len(ids)} for name,ids in [('early',early),('water',['water'])]}
    bg=None
    if L:
        crossing=[{**it,'remaining_ms':it['end_ms']-L} for it in intervals if it['task_id'] in early and it['operation']=='prepare' and it['start_ms']<L<it['end_ms']];reservations=[]
        for i,x in enumerate(ev):
            if x['type']!='action_reserved' or not x['timestamp_ms']<L<x['scheduled_start_ms']:continue
            outcomes=[(j,e) for j,e in enumerate(ev) if j>i and e['type'] in ('action_started','action_rejected') and e.get('proposal_id')==x['proposal_id'] and e['timestamp_ms']==x['scheduled_start_ms']]
            later=[(j,e) for j,e in enumerate(ev) if j>i and e['type']=='action_started' and e.get('proposal_id')==x['proposal_id']]
            ck(len(outcomes)==1 and len(later)<=1,sid+f' reservation e{i} unique scheduled outcome/start');j,e=outcomes[0]
            reservations.append({'task_id':x['task_id'],'proposal_id':x['proposal_id'],'reservation_event_index':i,'reserved_ms':x['timestamp_ms'],'planned_start_ms':x['scheduled_start_ms'],'scheduled_disposition_event_index':j,'scheduled_disposition':e['type'],'actual_start_ms':later[0][1]['timestamp_ms'] if later else None,'actual_start_event_index':later[0][0] if later else None,'counts_as_physical_load_at_L':False})
        water_events={k:next(({'event_index':i,'timestamp_ms':e['timestamp_ms']} for i,e in enumerate(ev) if e.get('task_id')=='water' and e['type']==k and e['timestamp_ms']>=L),None) for k in ('task_released','proposal_returned','action_started','action_completed','action_rejected','retry_queued','retry_scheduled')}
        bg={'release_ms':L,'interpretation':'descriptive_resource_background_not_causal_or_unavoidable','early_history':[{'task_id':tid,'start_ms':per[tid]['start_ms'],'end_ms':per[tid]['completion_ms'],'started_before_L':per[tid]['start_ms'] is not None and per[tid]['start_ms']<L,'event_indices':per[tid]['event_indices']} for tid in early],'crossing_actual_intervals':crossing,'physical_units_crossing_L':sum(it['units'] for it in crossing),'capacity_units':cap,'water_required_units':next(g['power_kw'] for g in ep['action_grounding'] if g['task_id']=='water' and g['operation']=='prepare'),'future_reservations_created_before_L':reservations,'first_water_events':water_events}
    out={**item,'subsets':subsets,'arrival_background':bg,'required_task_ids':E,'completed_task_ids':[tid for tid in E if tid in done],'denominators':{'required':n,'completed':c,'timely':t},'metrics':metrics,'auxiliary':{'conditional_timely_rate':t/c if c else None,'conditional_timely_null_reason':None if c else 'no_completed_requests','own_completed_means':{m:sum(per[tid][m] for tid in done)/c if c else None for m in tm}},'all_completed':c==n,'all_timely':t==n,'tasks':per,'event_counts':dict(count),'affected_task_ids':{k:sorted(v) for k,v in affected.items()},'event_reason_counts':{k:dict(v) for k,v in reasons.items()},'physical_intervals':intervals,'capacity_violation_intervals':safety,'preconditions_at_start':validity,'invalid_precondition_start_count':sum(not p['valid'] for p in validity),'coordination_compute_ms':None,'API_wallclock_ms':None,'unobserved_reason':'not_instrumented'}
    ck(eq(out,saved[sid]),sid+' all independently recounted saved fields');expected[sid]=out;raw[sid]=r
    evidence.append({'slot':sid,'source':item['source_path'],'pointer':item['source_pointer'],'verdict':'符合设计' if eq(out,saved[sid]) and not d['errors'] else '须修正','task_events':{tid:p['event_indices'] for tid,p in per.items()},'late_actual_crossing_intervals':bg['crossing_actual_intervals'] if bg else None,'late_future_reservations':bg['future_reservations_created_before_L'] if bg else None})
def effect(y):
    if len(y)==2:return {'right_minus_left':y[1]-y[0]}
    return {'capacity_effect_simultaneous':y[2]-y[0],'capacity_effect_late':y[3]-y[1],'release_effect_tight':y[1]-y[0],'release_effect_adequate':y[3]-y[2],'interaction':(y[3]-y[1])-(y[2]-y[0])}
def times(rs,subset=None):
    E=rs[0]['required_task_ids'];E=[t for t in E if subset is None or t in subset];K=[t for t in E if all(t in r['completed_task_ids'] for r in rs)]
    out={'required_task_ids':E,'completed_task_ids_by_arm':[[t for t in E if t in r['completed_task_ids']] for r in rs],'common_task_ids':K,'common_count':len(K),'required_count':len(E),'coverage':len(K)/len(E),'excluded_tasks':[{'task_id':t,'not_completed_arm_indices':[i for i,r in enumerate(rs) if t not in r['completed_task_ids']]} for t in E if t not in K],'eligible':bool(K),'null_reason':None if K else 'no_common_completed_requests','metrics':{}}
    for m in tm:
        y=[sum(r['tasks'][t][m] for t in K)/len(K) if K else None for r in rs]
        out['metrics'][m]={'arm_means':y,'effects':effect(y) if K else dict.fromkeys(effect([0]*len(rs)),None),'null_reason':None if K else 'no_common_completed_requests','per_task_values':{t:[r['tasks'][t][m] for r in rs] for t in K}}
    return out
def compare(s,four=False):
    rs=[expected[x] for x in s['slots']] if four else [expected[s['left']],expected[s['right']]];scalar={}
    for m in rules['primary_rates']+rules['process_allowlist']+['whole_house_completion_ms']:
        y=[r['metrics'][m] for r in rs];ok=m!='whole_house_completion_ms' or all(r['all_completed'] for r in rs)
        scalar[m]={'arm_values':y,'effects':effect(y) if ok else dict.fromkeys(effect([0]*len(rs)),None),'null_reason':None if ok else ('not_all_required_completed_in_four_cells' if four else 'not_all_required_completed_in_both_arms')}
    layers={name:{'required_task_ids':rs[0]['subsets'][name]['required_task_ids'],'denominators_by_arm':[r['subsets'][name]['denominators'] for r in rs],'rates':{m:{'arm_values':[r['subsets'][name][m] for r in rs],'effects':effect([r['subsets'][name][m] for r in rs])} for m in rules['primary_rates']}} for name in ('early','water')}
    return {**s,'scalar_comparison':scalar,'fixed_subset_service':layers,'conditional_time':times(rs),'conditional_subset_time':{name:times(rs,rs[0]['subsets'][name]['required_task_ids']) for name in layers},'whole_house_clock_note':'global_schedule_span_not_own_release_response_or_future_information_value'}
savedpairs=[p for k in ('policy','strong_rule','capacity','release') for p in read(B/f'pairs_{k}.json')['pairs']];plook={(p['kind'],p['left'],p['right']):p for p in savedpairs}
for p in plan['pairs']:ck(eq(compare(p),plook[(p['kind'],p['left'],p['right'])]),'pair independently computed '+str((p['kind'],p['left'],p['right'])))
groups=read(B/'four_cells.json')['groups']
for g,s in zip(plan['four_cells'],groups):ck(eq(compare(g,True),s),'fourcell all fourK and subset populations '+str(g['slots']))
diags={r['slot_id']:r for r in plan['diagnostic_runs']};diag_results=read(B/'information_diagnostics.json')['pairs'];diag_evidence=[]
for p,s in zip(plan['diagnostic_prefix_pairs'],diag_results):
    item=diags[p['diagnostic_slot']];diagnostic=read(R/item['source_path'])['runs'][int(item['source_pointer'].split('/')[-1])];main=raw[p['main_slot']];L=p['before_ms']
    def prefix(r):
        ci=[i for i,c in enumerate(r['calls']) if c['request']['current_time_ms']<L];ei=[i for i,e in enumerate(r['trace']['events']) if e['timestamp_ms']<L]
        return {'calls':[r['calls'][i] for i in ci],'events':[r['trace']['events'][i] for i in ei]},{'calls':ci,'events':ei}
    a,ai=prefix(main);b,bi=prefix(diagnostic);same=a==b;ck(same,'diagnostic full raw request decision event equality '+p['diagnostic_slot'])
    want={**p,'before_ms':L,'equal':same,'first_difference_channel':None,'main_prefix_indices':ai,'diagnostic_prefix_indices':bi,'performance_comparison':False,'diagnostic_source_path':item['source_path'],'diagnostic_source_pointer':item['source_pointer']}
    ck(eq(want,s),'diagnostic saved indices role '+p['diagnostic_slot']);diag_evidence.append(want)
summary=read(B/'summary.json');cfg={c['episode_id']:c for c in plan['configurations']}
for policy,p in summary['template_macro'].items():
    agg=[]
    for base,t in p['templates'].items():
        rs=[r for r in expected.values() if r['policy']==policy and cfg[r['episode_id']]['base_episode_id']==base];ck(len(rs)==4,'four macro slots '+policy+base)
        weights=[{'slot_id':r['slot_id'],'weight':'1/4','denominators':r['denominators']} for r in rs];rates={m:sum(r['metrics'][m] for r in rs)/4 for m in rules['primary_rates']}
        ck(eq(t,{'slot_weights':weights,'rates':rates}),'macro slot weights denominators values '+policy+base);agg.append(rates)
    ck(eq(p['rates'],{m:sum(r[m] for r in agg)/2 for m in rules['primary_rates']}) and p['template_weight']=='1/2','two template weights '+policy)
ck(len(expected)==32 and len(saved)==32 and len(savedpairs)==72 and len(groups)==8 and len(diag_results)==48,'all scope counts diagnostics isolated')
mani=read(B/'manifest.json')
for p,h in mani['artifact_sha256'].items():ck(sha(R/p)==h,'output hash '+p)
sys.path.insert(0,str(R));from homecoord_bench.task_revision.f2_aggregation_v1 import bundle,serialize
ck(all((R/p).read_text(encoding='utf-8')==serialize(v) for p,v in bundle().items()),'16 artifacts byte-level reproduction after independent checks')
files=[R/'homecoord_bench/task_revision/f2_aggregation_v1.py',R/'homecoord_bench/tests/test_f2_aggregation_v1.py',R/'docs/F2_AGGREGATION_V1_REVIEW_PACKET_2026-10-04.md',R/'docs/f2_statistical_contract_v1_20261004/freeze_20261004.json',*B.glob('*.json')]
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'run_evidence':evidence,'diagnostic_evidence':diag_evidence,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'tests':{'actual_run':36,'adapter':26,'contract':10,'result':'OK','full_suite_rerun':False},'rankings_created':False,'new_simulator_runs':0,'api_calls':0}
(O/'F2_AGGREGATION_V1_AUDIT_20261005.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'errors':out['errors'],'checks':len(checks),'runs':32,'pairs':72,'fourcells':8,'diagnostics':48},ensure_ascii=False))
