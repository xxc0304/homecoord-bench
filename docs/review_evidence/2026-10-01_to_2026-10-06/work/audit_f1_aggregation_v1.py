import json,hashlib,sys,copy,collections,math
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs');B=R/'docs/f1_aggregation_v1_20261004'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,msg):checks.append({'check':msg,'passed':bool(v)})
def eq(a,b):
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(eq(v,b[k]) for k,v in a.items())
    if isinstance(a,list):return isinstance(b,list) and len(a)==len(b) and all(eq(v,w) for v,w in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,abs_tol=1e-9,rel_tol=1e-12)
    return a==b
def get(s,p):
    for k in p.split('.'):s=s.get(k) if isinstance(s,dict) else None
    return s
def put(s,p,v):
    ks=p.split('.')
    for k in ks[:-1]:s=s.setdefault(k,{})
    s[ks[-1]]=copy.deepcopy(v)
def holds(s,r):
    a,b=get(s,r['path']),r['value'];op=r['op']
    return {'eq':lambda:a==b,'neq':lambda:a!=b,'lt':lambda:a is not None and a<b,'lte':lambda:a is not None and a<=b,'gt':lambda:a is not None and a>b,'gte':lambda:a is not None and a>=b,'between':lambda:a is not None and b[0]<=a<=b[1]}[op]()
freeze=read(R/'docs/f1_statistical_contract_v2_20261004/freeze_20261004.json');prior=read(O/'F1_CONTRACT_V2_CORRECTION_AUDIT_20261004.json')
ck(freeze['reviewed_sha256']=={p.replace('\\','/'):h for p,h in prior['reviewed_sha256'].items()},'freeze eight materials exactly prior independent locks')
for p,h in {**freeze['reviewed_sha256'],**freeze['source_sha256']}.items():ck(sha(R/p)==h,'frozen material '+p)
for k in ('review','review_audit'):ck(sha(Path(freeze[k+'_path']))==freeze[k+'_sha256'],'freeze independent '+k+' actual hash')
author=read(B/'author_verification.json')
for p,h in author['protected_sha256'].items():ck(sha(R/p)==h,'author protected '+p)
ck(len(author['protected_sha256'])==115,'115 protected hashes')
plan=read(R/freeze['plan_path']);rules=plan['metric_rules'];tm=rules['four_cell_allowlist']['same_four_cell_completed_population'];rn=rules['four_cell_allowlist']['run_event_or_process'];cellnames=('tight_base','tight_loose','adequate_base','adequate_loose')
saved={r['slot_id']:r for p in B.glob('D-F1-*.json') for r in read(p)['runs']}; expected={};evidence=[]
for item in plan['runs']:
    sid=item['slot_id'];doc=read(R/item['source_path']) if 'source_path' in item else read(R/next(c['source_path'] for c in plan['configurations'] if c['episode_id']==item['episode_id']))
    ep=doc['episode'];r=doc['runs'][int(item['source_pointer'].split('/')[-1])];tasks={t['task_id']:t for t in ep['task_stream']};events=r['trace']['events']
    ck((r['episode_id'],r['policy'],r['arrival_order_index'])==(item['episode_id'],item['policy'],item['order']),sid+' identity')
    calls={c['request']['task']['task_id']:c for c in r['calls']};proposals={a['proposal_id']:(tid,a) for tid,c in calls.items() for a in c['decision']['actions']}
    ck(set(calls)==set(tasks),sid+' complete calls')
    state=copy.deepcopy(ep['initial_state']['values']);version=ep['initial_state']['version'];active={};starts={};done={};rel={};ret={};intervals=[];pre={};validity=[];count=collections.Counter();affected=collections.defaultdict(set);reasons=collections.defaultdict(collections.Counter);last=-1
    for i,x in enumerate(events):
        kind=x['type'];at=x['timestamp_ms'];tid=x['task_id'];pid=x.get('proposal_id');ck(at>=last,sid+f' e{i} time');last=at
        count[kind]+=1;affected[kind].add(tid)
        if 'reason' in x:reasons[kind][str(x['reason'])]+=1
        if kind=='task_released':
            ck(at==tasks[tid]['release_at_ms'] and x['request_id']==calls[tid]['request']['request_id'],sid+f' e{i} release');rel[tid]=(at,i)
        elif kind=='proposal_returned':
            ck(x['request_id']==calls[tid]['request']['request_id'] and at-rel[tid][0]==calls[tid]['logical_latency_ms'],sid+f' e{i} return');ret[tid]=(at,i)
        elif kind=='coordination_decision':
            k='coordination_'+x['decision'];count[k]+=1;affected[k].add(tid)
        elif kind=='state_update':
            ck(x['source']=='action_started',sid+f' e{i} patch source');pre[tid]=copy.deepcopy(state)
            for p,v in x['patch'].items():put(state,p,v)
            version+=1;ck(version==x['new_state_version'],sid+f' e{i} version')
        elif kind=='action_started':
            g=next(g for g in ep['action_grounding'] if (g['task_id'],g['target'],g['operation'])==(tid,x['target'],x['operation']))
            ag=next(a for a in ep['agents'] if a['agent_id']==tasks[tid]['agent_id']);tool=next(t for t in ep['tool_catalog'] if (t['agent_id'],t['target'],t['operation'])==(x['agent_id'],x['target'],x['operation']))
            ck(pid not in active and x['agent_id']==tasks[tid]['agent_id'] and tid in ret and at>=ret[tid][0],sid+f' e{i} start lifecycle')
            ck(pid in proposals and proposals[pid][0]==tid and (proposals[pid][1]['target'],proposals[pid][1]['operation'])==(x['target'],x['operation']),sid+f' e{i} actual proposal identity')
            ck(tool['tool_name'] in ag['tools'] and 'devices.'+x['target'] in ag['writable_resources'],sid+f' e{i} permission')
            ck(all(x[k]==g[k] for k in ('duration_ms','power_kw','start_effects','completion_effects')) and x['state_version_at_start']==version,sid+f' e{i} grounding/version')
            prestate=pre.pop(tid,state);validity.append({'task_id':tid,'event_index':i,'valid':all(holds(prestate,q) for q in x['requires'])})
            active[pid]=(i,x)
            if any(all(x.get(k)==v for k,v in spec.items()) for spec in tasks[tid]['acceptable_actions']):starts[tid]=(i,x)
        elif kind=='action_completed':
            ck(pid in active,sid+f' e{i} true active receipt');j,s=active.pop(pid)
            ck(all(x[k]==s[k] for k in ('task_id','agent_id','target','operation')) and at==s['timestamp_ms']+s['duration_ms'] and x['effects']==s['completion_effects'],sid+f' e{i} receipt identity/time/effects')
            intervals.append({'task_id':tid,'proposal_id':pid,'start_event_index':j,'completion_event_index':i,'start_ms':s['timestamp_ms'],'end_ms':at,'units':s['power_kw']})
            for p,v in x['effects'].items():put(state,p,v)
            version+=1;ck(version==x['new_state_version'],sid+f' e{i} completion version')
            if tid in starts and starts[tid][1]['proposal_id']==pid:done[tid]=(i,x)
    ck(not active and not pre and state==r['trace']['final_state'] and version==r['trace']['final_state_version'],sid+' final real state and closed intervals')
    # Integrate interval endpoints; no transient same-timestamp active dictionary is treated as positive duration.
    bounds=sorted({v for it in intervals for v in (it['start_ms'],it['end_ms'])});capacity=ep['home']['resources']['max_power_kw'];harm=0;excess=0
    for l,h in zip(bounds,bounds[1:]):
        load=sum(it['units'] for it in intervals if it['start_ms']<=l<it['end_ms'])
        if load>capacity:harm+=h-l;excess+=(h-l)*(load-capacity)
    n=len(tasks);c=len(done); per={}
    for tid,t in tasks.items():
        R0,ri=rel[tid];P,pi=ret[tid];S=starts[tid][1]['timestamp_ms'] if tid in starts else None;F=done[tid][1]['timestamp_ms'] if tid in done else None
        per[tid]={'release_ms':R0,'deadline_ms':t['completion_deadline_ms'],'proposal_return_ms':P,'start_ms':S,'completion_ms':F,'started':S is not None,'completed':F is not None,'timely':F is not None and F<=t['completion_deadline_ms'],'logical_proposal_return_ms':P-R0,'proposal_to_start_ms':S-P if S is not None else None,'task_start_wait_ms':S-R0 if S is not None else None,'execution_ms':F-S if F is not None else None,'completion_latency_ms':F-R0 if F is not None else None,'tardiness_ms':max(0,F-t['completion_deadline_ms']) if F is not None else None,'event_indices':{'release':ri,'return':pi,'start':starts[tid][0] if tid in starts else None,'completion':done[tid][0] if tid in done else None},'null_reasons':{'start':None if S is not None else 'not_started','completion':None if F is not None else 'not_completed'},'coordination_compute_ms':None,'API_wallclock_ms':None,'unobserved_reason':'not_instrumented'}
    nt=sum(p['timely'] for p in per.values());metrics={'service_rate':c/n,'timely_service_rate':nt/n,'executed_capacity_violation_duration_ms':harm,'excess_resource_unit_ms':excess,'whole_house_completion_ms':max(p['completion_ms'] for p in per.values())-ep['episode_release_at_ms'] if c==n else None}
    for m in rn[2:]:metrics[m]=count[{'reservation_count':'action_reserved','actual_start_count':'action_started'}.get(m,m.removesuffix('_count'))]
    exp={**item,'required_task_ids':list(tasks),'completed_task_ids':[t for t in tasks if t in done],'denominators':{'required':n,'completed':c,'timely':nt},'metrics':metrics,'auxiliary':{'conditional_timely_rate':nt/c if c else None,'conditional_timely_null_reason':None if c else 'no_completed_requests','own_completed_means':{m:sum(per[t][m] for t in done)/c if c else None for m in tm}},'all_completed':c==n,'all_timely':nt==n,'tasks':per,'event_counts':dict(count),'affected_task_ids':{k:sorted(v) for k,v in affected.items()},'event_reason_counts':{k:dict(v) for k,v in reasons.items()},'physical_intervals':intervals,'preconditions_at_start':validity,'invalid_precondition_start_count':sum(not p['valid'] for p in validity),'coordination_compute_ms':None,'API_wallclock_ms':None,'unobserved_reason':'not_instrumented'}
    actual={k:v for k,v in saved[sid].items() if k!='capacity_violation_intervals'}
    ck(eq(exp,actual),sid+' independent all run fields')
    ck(sum(it['end_ms']-it['start_ms'] for it in saved[sid]['capacity_violation_intervals'])==harm,sid+' violation intervals duration')
    safety=[];prev=0
    for i,x in enumerate(events):
        now=x['timestamp_ms'];load=sum(it['units'] for it in intervals if it['start_ms']<=prev<it['end_ms'])
        if now>prev and load>capacity:safety.append({'start_ms':prev,'end_ms':now,'load_units':load,'capacity_units':capacity,'next_event_index':i})
        prev=now
    ck(safety==saved[sid]['capacity_violation_intervals'],sid+' exact half-open capacity interval evidence')
    expected[sid]=exp;evidence.append({'slot_id':sid,'source_pointer':item['source_pointer'],'episode_id':ep['episode_id'],'policy':item['policy'],'order':item['order'],'tasks':{t:{'events':p['event_indices'],'start_ms':p['start_ms'],'completion_ms':p['completion_ms']} for t,p in per.items()},'verdict':'符合设计' if eq(exp,actual) else '须修正'})
def times(rows):
    E=rows[0]['required_task_ids'];K=[t for t in E if all(t in r['completed_task_ids'] for r in rows)]
    o={'required_task_ids':E,'completed_task_ids_by_arm':[r['completed_task_ids'] for r in rows],'common_task_ids':K,'coverage':len(K)/len(E),'metrics':{}}
    for m in tm:
        y=[sum(r['tasks'][t][m] for t in K)/len(K) if K else None for r in rows]
        v=(y[1]-y[0]) if len(rows)==2 and K else (y[3]-y[1])-(y[2]-y[0]) if K else None
        o['metrics'][m]={'arm_means':y,'value':v,'null_reason':None if K else 'no_common_completed_requests','per_task_values':{t:[r['tasks'][t][m] for r in rows] for t in K}}
        if len(rows)==4:o['metrics'][m]['effects_on_identical_K']={k:(y[b]-y[a] if K else None) for k,a,b in [('capacity_effect_base',0,2),('capacity_effect_loose',1,3),('deadline_effect_tight',0,1),('deadline_effect_adequate',2,3)]}
    return o
savedpairs=[p for kind in ('policy','capacity','deadline','return_order') for p in read(B/f'pairs_{kind}.json')['pairs']]
pairlookup={(p['kind'],p['left'],p['right']):p for p in savedpairs}
for p in plan['pairs']:
    a,b=expected[p['left']],expected[p['right']];scalar={}
    for m in list(rules['four_cell_allowlist']['fixed_E_rates'])+rn+['whole_house_completion_ms']:
        x,y=a['metrics'][m],b['metrics'][m];ok=x is not None and y is not None
        scalar[m]={'left':x,'right':y,'value':y-x if ok else None,'null_reason':None if ok else 'not_all_required_completed_in_both_arms'}
    want={**p,'scalar_deltas':scalar,'conditional_time':times([a,b])}
    ck(eq(want,pairlookup[(p['kind'],p['left'],p['right'])]),'pair independent '+str((p['kind'],p['left'],p['right'])))
groups=read(B/'four_cells.json')['groups']
for g,savedg in zip(plan['four_cells'],groups):
    rs=[expected[s] for s in g['slots']];E=rs[0]['required_task_ids'];K=[t for t in E if all(t in r['completed_task_ids'] for r in rs)];full=all(r['completed_task_ids']==E for r in rs)
    population={'required_task_ids':E,'completed_task_ids_by_cell':{c:r['completed_task_ids'] for c,r in zip(cellnames,rs)},'common_task_ids':K,'common_count':len(K),'required_count':len(E),'coverage':len(K)/len(E),'excluded_tasks':[{'task_id':t,'reason':'not_completed_in_all_four_cells','not_completed_cells':[c for c,r in zip(cellnames,rs) if t not in r['completed_task_ids']]} for t in E if t not in K],'eligible':bool(K),'null_reason':None if K else 'no_common_completed_requests','all_E_completed_in_all_four_cells':full}
    scalars={}
    for m in list(rules['four_cell_allowlist']['fixed_E_rates'])+rn+['whole_house_completion_ms']:
        y=[r['metrics'][m] for r in rs];eligible=m!='whole_house_completion_ms' or full
        scalars[m]={'cell_values':y,'interaction':(y[3]-y[1])-(y[2]-y[0]) if eligible else None,**{k:y[b]-y[a] if eligible else None for k,a,b in [('capacity_effect_base',0,2),('capacity_effect_loose',1,3),('deadline_effect_tight',0,1),('deadline_effect_adequate',2,3)]},'null_reason':None if eligible else 'not_all_required_completed_in_four_cells'}
    ck(eq({**g,'population':population,'scalar_effects':scalars,'conditional_time':times(rs)},savedg),'fourcell independent '+str(g['slots']))
summary=read(B/'summary.json');cmap={c['episode_id']:c['base_episode_id'] for c in plan['configurations']}
for policy,ps in summary['template_macro'].items():
    means=[]
    for base,bs in ps['templates'].items():
        rows=[r for r in expected.values() if r['policy']==policy and cmap[r['episode_id']]==base];ck(len(rows)==12,policy+base+' twelve expected slots')
        ck(bs['slot_weights']==[{'slot_id':r['slot_id'],'weight':'1/12','denominators':r['denominators']} for r in rows],policy+base+' exact weights and coverage')
        rates={m:sum(r['metrics'][m] for r in rows)/12 for m in ('service_rate','timely_service_rate')};ck(eq(bs['rates'],rates),policy+base+' equal12 main rates');means.append(rates)
    ck(ps['template_weight']=='1/2' and eq(ps['rates'],{m:sum(r[m] for r in means)/2 for m in ('service_rate','timely_service_rate')}),policy+' equal2templates')
ck(len(expected)==72 and len(savedpairs)==168 and len(groups)==18,'72 168 18 retained')
manifest=read(B/'manifest.json')
for p,h in manifest['artifact_sha256'].items():ck(sha(R/p)==h,'saved artifact hash '+p)
sys.path.insert(0,str(R));from homecoord_bench.task_revision.f1_aggregation_v1 import bundle,serialize
ck(all((R/p).read_text(encoding='utf-8')==serialize(v) for p,v in bundle().items()),'exact saved artifact regeneration')
files=[R/'homecoord_bench/task_revision/f1_aggregation_v1.py',R/'homecoord_bench/tests/test_f1_aggregation_v1.py',R/'docs/F1_AGGREGATION_V1_REVIEW_PACKET_2026-10-04.md',R/'docs/f1_statistical_contract_v2_20261004/freeze_20261004.json',*B.glob('*.json')]
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'run_evidence':evidence,'reviewed_sha256':{str(p.relative_to(R)):sha(p) for p in files},'tests':{'actual_run':37,'adapter':20,'contracts':17,'result':'OK','full_suite_rerun':False},'rankings_created':False,'api_calls':0,'new_simulator_runs':0}
(O/'F1_AGGREGATION_V1_AUDIT_20261004.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'errors':out['errors'],'checks':len(checks),'runs':len(expected),'pairs':len(savedpairs),'fourcells':len(groups)},ensure_ascii=False))
