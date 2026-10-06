import json,copy,hashlib,sys,collections,math
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');B=R/'docs/f2_reservation_ablation_v1_20261005';O=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def obj(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
checks=[]
def ck(v,s):checks.append({'check':s,'passed':bool(v)})
def eq(a,b):
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(eq(v,b[k]) for k,v in a.items())
    if isinstance(a,list):return isinstance(b,list) and len(a)==len(b) and all(eq(v,w) for v,w in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,abs_tol=1e-8,rel_tol=1e-12)
    return a==b
lock=read(B/'preregistration_lock_revision3.json');plan=read(B/'plan.json');verification=read(B/'verification_record.json');stat=read(B/'statistics.json')
for section in ('new_design_code_sha256','protected_sha256'):
    for p,h in lock[section].items():ck(sha(R/p)==h,'current lock '+p)
ck(len(lock['protected_sha256'])==835,'835 protected files')
for p,h in verification['artifact_sha256'].items():ck(sha(R/p)==h,'submission '+p)
for p,h in read(O/'SMALL_VALIDATION_V1_EXECUTION_AUDIT_20261005.json')['reviewed_sha256'].items():ck(sha(R/p)==h,'previous independent acceptance '+p)
for key,file in [('original_failed_lock_sha256','preregistration_lock.json'),('original_failed_entry_sha256','failed_preflight_entry_v1.py'),('preflight_failure_sha256','preflight_failure_v1.json'),('superseded_revision2_lock_sha256','preregistration_lock_revision2.json'),('superseded_revision2_entry_sha256','failed_preflight_entry_revision2.py'),('revision2_failure_sha256','preflight_failure_revision2.json')]:ck(lock[key]==sha(B/file),'preserved '+file)
for filename in ('preregistration_lock.json','preregistration_lock_revision2.json'):
    old=read(B/filename)
    for path in ('homecoord_bench/task_revision/event_simulator_reservation_v1.py','docs/F2_RESERVATION_ABLATION_V1_PREREG_2026-10-05.md','docs/f2_reservation_ablation_v1_20261005/plan.json'):ck(old['new_design_code_sha256'][path]==sha(R/path),'preflight unchanged engine contract grid '+filename+'/'+path)
src=Path('work/audit_f2_v7.py').read_text(encoding='utf8').split('details=[]')[0].replace("for k,v in r['audit']['recount'].items():","for k,v in r.get('audit',{}).get('recount',{}).items():")
ns={};exec(compile(src,'prior_independent_public_inputs_physical_replay','exec'),ns)
ck(not ns['hash_errors'],'old F2 sources unchanged')
extra={'reservation_review_started','reservation_review_committed','reservation_invalidated','reservation_callback_suppressed'}
tm=['task_start_wait_ms','proposal_to_start_ms','execution_ms','completion_latency_ms','tardiness_ms']
def earliest(now,duration,units,intervals,cap):
    candidates=sorted({now}|{x['end'] for x in intervals if x['end']>=now})
    for start in candidates:
        end=start+duration;bounds=sorted({start,end}|{v for x in intervals for v in (x['start'],x['end']) if start<v<end})
        if all(units+sum(x['units'] for x in intervals if x['start']<=a<x['end'])<=cap for a,b in zip(bounds,bounds[1:])):return start
    raise AssertionError('no constructive slot')
def replay(ep,r,label):
    d=ns['audit'](ep,r,label,0,'mechanism');ck(not d['errors'],label+' independent physical/input/receipt replay '+str(d['errors']))
    ev=r['trace']['events'];tasks={t['task_id']:t for t in ep['task_stream']};ground={g['task_id']:g for g in ep['action_grounding'] if g['operation']=='prepare'};cap=ep['home']['resources']['max_power_kw']
    state=copy.deepcopy(ep['initial_state']['values']);version=ep['initial_state']['version'];live={};gens={};invalid={};suppressed=set();active={};rel={};ret={};starts={};done={};reviewstart=reviewcommit=None;batch=[];count=collections.Counter()
    for ci,call in enumerate(r['calls']):
        q=call['request'];tool=next(x for x in q['available_actions'] if x['operation']=='prepare')
        dec={'response_type':'action_proposal','actions':[{'proposal_id':q['request_id']+':0','target':tool['target'],'operation':'prepare','parameters':[],'based_on_state_version':q['state_version'],'requires':[{**z,'range_min':None,'range_max':None} for z in tool['preconditions']],'estimated_duration_ms':tool['cost_contract']['duration_ms'],'estimated_power_kw':tool['cost_contract']['resource_units']}],'accepted_proposal_ids':[],'rejected_proposal_ids':[],'defer_until_ms':None,'reason_code':'goal_progress'}
        ck(call['decision']==dec,label+f' call{ci} exact public capability decision')
    for i,x in enumerate(ev):
        k=x['type'];t=x['timestamp_ms'];tid=x.get('task_id');pid=x.get('proposal_id');gen=x.get('reservation_generation');count[k]+=1
        if k=='task_released':rel[tid]=(t,i)
        if k=='proposal_returned':ret[tid]=(t,i)
        if k=='reservation_review_started':
            ck(reviewstart is None and set(rel)==set(ret) and 'water' in ret and t==ret['water'][0] and x['duration_ms']==r['review_delay_ms'] and x['released_task_ids']==sorted(rel) and x['returned_task_ids']==sorted(ret),label+f' e{i} common trigger released-only')
            reviewstart=[t,i]
        if k=='reservation_review_committed':
            ck(reviewcommit is None and t==reviewstart[0]+r['review_delay_ms'] and x['state']==state and x['state_version']==version,label+f' e{i} actual commit state/clock')
            future={p:z for p,z in live.items() if p not in active};ck({z['proposal_id'] for z in x['running_actions']}==set(active) and {z['proposal_id'] for z in x['unstarted_reservations']}==set(future),label+f' e{i} physical versus future snapshot')
            ck(x['released_task_ids']==sorted(rel) and x['returned_task_ids']==sorted(ret) and x['ready_task_ids']==['water'],label+f' e{i} full released ready snapshot')
            for z in x['running_actions']+x['unstarted_reservations']:
                rr=live[z['proposal_id']];g=ground[z['task_id']]
                ck(z['reservation_generation']==rr['reservation_generation'] and z['timestamp_ms']==rr['scheduled_start_ms'] and z['duration_ms']==g['duration_ms'] and z['power_kw']==g['power_kw'] and z['target']==g['target'] and z['operation']=='prepare',label+f' e{i} snapshot action identity costs')
            reviewcommit=[t,i]
        if k=='reservation_invalidated':
            ck(r['arm']=='replan' and t==reviewcommit[0] and pid in live and pid not in active and tid not in starts,label+f' e{i} only physically unstarted invalidation')
            rr=live.pop(pid);ck(rr['reservation_generation']==gen and x['old_scheduled_start_ms']==rr['scheduled_start_ms']>=t,label+f' e{i} exact invalidated generation')
            invalid[(pid,gen)]=(rr,i)
        if k=='reservation_callback_suppressed':
            key=(pid,gen);ck(key in invalid and key not in suppressed and t==invalid[key][0]['scheduled_start_ms'],label+f' e{i} stale callback once at old time');suppressed.add(key)
        if k=='action_reserved':
            g=ground[tid];old=gens.get(pid,0);ck(pid not in live and tid not in starts and gen==old+1 and tid in ret and t>=ret[tid][0],label+f' e{i} new unique proposal generation')
            intervals=[{'start':z['scheduled_start_ms'],'end':z['scheduled_start_ms']+z['duration_ms'],'units':z['power_kw']} for z in live.values()]
            es=earliest(t+100,g['duration_ms'],g['power_kw'],intervals,cap)
            ck(x['scheduled_start_ms']==es and x['duration_ms']==g['duration_ms'] and x['power_kw']==g['power_kw'],label+f' e{i} independent earliest safe capacity reservation')
            gens[pid]=gen;live[pid]=x
            batch.append((t,tid))
        if k=='state_update':
            for p,v in x['patch'].items():ns['put'](state,p,v)
            version+=1
        if k=='action_started':
            ck(pid in live and pid not in active and gen==live[pid]['reservation_generation'] and t==live[pid]['scheduled_start_ms'] and tid not in starts,label+f' e{i} only live callback actually starts')
            active[pid]=x;starts[tid]=(t,i)
        if k=='action_completed':
            s=active.pop(pid);ck(gen==s['reservation_generation'] and (pid,gen) not in invalid,label+f' e{i} matched live generation receipt');done[tid]=(t,i);live.pop(pid)
            for p,v in x['effects'].items():ns['put'](state,p,v)
            version+=1
    ck(not live and not active and suppressed==set(invalid),label+' all physical and reservation lifecycles closed')
    for timestamp in sorted({t for t,tid in batch}):
        ids=[tid for t,tid in batch if t==timestamp];order=sorted(ids,key=lambda tid:(tasks[tid]['completion_deadline_ms'],-tasks[tid]['priority'],ret[tid][0],tid))
        ck(ids==order,label+f' at{timestamp} identical EDF sorting function')
    per={}
    for tid,t in tasks.items():
        R0,ri=rel[tid];P,pi=ret[tid];S,si=starts.get(tid,(None,None));F,fi=done.get(tid,(None,None))
        per[tid]={'release_ms':R0,'deadline_ms':t['completion_deadline_ms'],'proposal_return_ms':P,'start_ms':S,'completion_ms':F,'completed':F is not None,'timely':F is not None and F<=t['completion_deadline_ms'],'task_start_wait_ms':S-R0 if S is not None else None,'proposal_to_start_ms':S-P if S is not None else None,'execution_ms':F-S if F is not None else None,'completion_latency_ms':F-R0 if F is not None else None,'tardiness_ms':max(0,F-t['completion_deadline_ms']) if F is not None else None,'event_indices':{'release':ri,'return':pi,'start':si,'completion':fi}}
    intervals=[{'task_id':z['task_id'],'proposal_id':ev[z['start_event']]['proposal_id'],'reservation_generation':ev[z['start_event']]['reservation_generation'],'start_ms':z['start_ms'],'end_ms':z['end_ms'],'units':z['units'],'start_event_index':z['start_event'],'completion_event_index':z['end_event']} for z in d['intervals']]
    exposure=integral=0
    bounds=sorted({v for z in intervals for v in (z['start_ms'],z['end_ms'])})
    for a,b in zip(bounds,bounds[1:]):
        load=sum(z['units'] for z in intervals if z['start_ms']<=a<z['end_ms']);exposure+=(b-a) if load>cap else 0;integral+=max(0,load-cap)*(b-a)
    E=list(tasks);nc=len(done);nt=sum(z['timely'] for z in per.values());subsets={n:{'required_task_ids':ids,'required':len(ids),'completed':sum(per[t]['completed'] for t in ids),'timely':sum(per[t]['timely'] for t in ids)} for n,ids in [('early',[t for t in E if t!='water']),('water',['water'])]}
    return {'required_task_ids':E,'completed_task_ids':[t for t in E if t in done],'all_completed':nc==4,'denominators':{'required':4,'completed':nc,'timely':nt},'metrics':{'service_rate':nc/4,'timely_service_rate':nt/4,'whole_house_completion_ms':max(z['completion_ms'] for z in per.values())-ep['episode_release_at_ms'] if nc==4 else None,'executed_capacity_violation_duration_ms':exposure,'excess_resource_unit_ms':integral},'conditional_timely_rate':nt/nc if nc else None,'subsets':subsets,'tasks':per,'physical_intervals':intervals,'review_start':reviewstart,'review_commit':reviewcommit,'event_counts':dict(count),'invalidated_reservations':[{'proposal_id':pid,'generation':gen,'invalidation_event_index':i,'old_reservation':rr} for (pid,gen),(rr,i) in invalid.items()]}
def times(rows,subset=None):
    E=[t for t in rows[0]['required_task_ids'] if subset is None or t in subset];K=[t for t in E if all(t in r['completed_task_ids'] for r in rows)]
    out={'required_task_ids':E,'completed_task_ids_by_arm':[[t for t in E if t in r['completed_task_ids']] for r in rows],'common_task_ids':K,'common_count':len(K),'required_count':len(E),'coverage':len(K)/len(E),'excluded_tasks':[{'task_id':t,'not_completed_arm_indices':[i for i,r in enumerate(rows) if t not in r['completed_task_ids']]} for t in E if t not in K],'eligible':bool(K),'null_reason':None if K else 'no_common_completed_requests','metrics':{}}
    for m in tm:
        vals=[sum(r['tasks'][t][m] for t in K)/len(K) if K else None for r in rows];out['metrics'][m]={'arm_means':vals,'effects':{'right_minus_left':vals[1]-vals[0] if K else None},'null_reason':None if K else 'no_common_completed_requests','per_task_values':{t:[r['tasks'][t][m] for r in rows] for t in K}}
    return out
def pair(ep,runs,rows):
    ci=[z['review_commit'][1] for z in rows];prefixes=[r['trace']['events'][:i+1] for r,i in zip(runs,ci)];commit=prefixes[0][-1];ck(prefixes[0]==prefixes[1] and runs[0]['calls']==runs[1]['calls'],ep['episode_id']+' complete calls and prefix through snapshot equal')
    running=[c['task_id'] for c in commit['running_actions']];future=[c['task_id'] for c in commit['unstarted_reservations']]
    ck(not rows[0]['invalidated_reservations'] and {x['old_reservation']['task_id'] for x in rows[1]['invalidated_reservations']}==set(future),ep['episode_id']+' all and only unstarted invalidated')
    ck(all(rows[0]['tasks'][t]['start_ms']==rows[1]['tasks'][t]['start_ms'] and rows[0]['tasks'][t]['completion_ms']==rows[1]['tasks'][t]['completion_ms'] for t in running),ep['episode_id']+' started services unchanged')
    delta={}
    for tid in rows[0]['required_task_ids']:
        a,b=[r['tasks'][tid] for r in rows];delta[tid]={m:b[m]-a[m] if a[m] is not None and b[m] is not None else None for m in ['start_ms','completion_ms']+tm};delta[tid].update(completed_by_arm=[a['completed'],b['completed']],timely_by_arm=[a['timely'],b['timely']])
    rates={m:{'arm_values':[r['metrics'][m] for r in rows],'right_minus_left':rows[1]['metrics'][m]-rows[0]['metrics'][m]} for m in ('service_rate','timely_service_rate')};house=[r['metrics']['whole_house_completion_ms'] for r in rows]
    return {'calls_equal':True,'full_prefix_through_commit_equal':True,'prefix_sha256':obj(prefixes[0]),'commit_event_indices':ci,'commit_ms':commit['timestamp_ms'],'running_task_ids':running,'unstarted_task_ids':future,'running_service_intervals_unchanged':True,'metrics':rates,'whole_house':{'arm_values':house,'right_minus_left':house[1]-house[0] if None not in house else None,'null_reason':None if None not in house else 'not_all_E_completed_in_both_arms'},'per_task_deltas':delta,'common_K_time':times(rows),'subset_common_K_time':{n:times(rows,rows[0]['subsets'][n]['required_task_ids']) for n in ('early','water')},'audits':rows}
details=[];gate=read(B/'baseline_gate_revision3.json');baseline=[]
ck(len(plan['configurations'])==8 and plan['scope']=={'configurations':8,'runs':16,'pairs':8,'primary_pairs':4,'sensitivity_pairs':4,'information_diagnostic_runs':24},'exact static scope')
sources=[e for e in ns['eps'].values() if e['episode_id'].endswith('-late')]
ck([(c['source_episode_id'],c['review_delay_ms']) for c in plan['configurations']]==[(e['episode_id'],cost) for e in sources for cost in (0,100)],'grid exact 4 sources by two common costs')
for i,c in enumerate(plan['configurations']):
    doc=read(B/f'config_{i:02d}.json');e=copy.deepcopy(ns['eps'][c['source_episode_id']]);ck(obj(e)==c['source_sha256'],'source input '+c['config_id']);e['episode_id']=c['config_id']
    ck(doc['input']==e and doc['config']==c and doc['input_sha256']==obj(e) and doc['lock_sha256']==sha(B/'preregistration_lock_revision3.json'),c['config_id']+' only private identity change and lock')
    ck([(r['arm'],r['review_delay_ms'],r['policy']) for r in doc['runs']]==[(arm,c['review_delay_ms'],'DeadlineAwareCoordinator') for arm in ('retain','replan')],c['config_id']+' same policy arm cost')
    rows=[replay(e,r,c['config_id']+'/'+r['arm']) for r in doc['runs']];p=pair(e,doc['runs'],rows);ck(eq(p,doc['pair']),c['config_id']+' independent full saved pair/audits');ck(eq(p,stat['configurations'][i]['pair']),c['config_id']+' independent statistics pair')
    if c['role']=='primary':
        old=next(r for r in read(R/('homecoord_bench/task_revision/fixtures/f2_v7/runs/'+c['source_episode_id']+'.json'))['runs'] if r['policy']=='DeadlineAwareCoordinator');r=doc['runs'][0];trace=copy.deepcopy(r['trace']);trace['events']=[{k:v for k,v in x.items() if k!='reservation_generation'} for x in trace['events'] if x['type'] not in extra];trace['event_count']=len(trace['events']);trace['episode_id']=old['trace']['episode_id'];trace['trace_id']=old['trace']['trace_id'];result=copy.deepcopy(r['result']);result['episode_id']=old['result']['episode_id']
        ck(trace==old['trace'] and r['calls']==old['calls'] and result==old['result'],c['config_id']+' four newly retained baselines full projected historical match');g=next(g for g in gate['baselines'] if g['config_id']==c['config_id']);ck(g['run']==r and eq(g['audit'],rows[0]),c['config_id']+' primary retain is fresh gate run no duplicate');baseline.append(c['config_id'])
    running=doc['runs'][0]['trace']['events'][rows[0]['review_commit'][1]]['running_actions'];ints=[{'start':z['timestamp_ms'],'end':z['timestamp_ms']+z['duration_ms'],'units':z['power_kw']} for z in running];water=next(g for g in e['action_grounding'] if g['task_id']=='water' and g['operation']=='prepare');bound=earliest(rows[0]['review_commit'][0]+100,water['duration_ms'],water['power_kw'],ints,e['home']['resources']['max_power_kw'])
    details.append({'config_id':c['config_id'],'template':c['template'],'capacity_arm':c['capacity_arm'],'review_delay_ms':c['review_delay_ms'],'verdict':'符合设计','independent_pair':p,'fixed_prefix_water_earliest_start_ms':bound,'fixed_prefix_water_earliest_finish_ms':bound+water['duration_ms']})
diag=[]
for i in range(4):
    doc=read(B/f'diagnostic_{i:02d}.json');main=read(B/f'config_{2*i:02d}.json');seen=set();cutoff=next(t['release_at_ms'] for t in main['input']['task_stream'] if t['task_id']=='water')
    for rec in doc['records']:
        key=(rec['arm'],rec['case']);ck(key not in seen,'unique diagnostic '+str((i,key)));seen.add(key);r=rec['run'];m=next(r for r in main['runs'] if r['arm']==rec['arm']);pre=lambda x:{'calls':[c for c in x['calls'] if c['request']['current_time_ms']<cutoff],'events':[e for e in x['trace']['events'] if e['timestamp_ms']<cutoff]}
        changed=copy.deepcopy(main['input']);w=next(t for t in changed['task_stream'] if t['task_id']=='water');changed['episode_id']='SECRET-future-condition';changed['base_episode_id']='SECRET-private-base';changed['goals'].append({'path':'SECRET-future-goal','op':'eq','value':True});changed['initial_state']['values']['coordination_context']['secret']='SECRET-future-context';changed['home']['resources']['task_power_bounds_kw']['water']=999
        for tool in changed['tool_catalog']:tool['description']='SECRET-future-description'
        for agent in changed['agents']:agent['private_note']='SECRET-future-agent'
        if rec['case']=='different_arrival':w['release_at_ms']+=30000;w['completion_deadline_ms']+=30000;changed['exogenous_events'][0]['at_ms']=w['release_at_ms']
        if rec['case']=='different_request':w['goal']='SECRET-future-goal';w['priority']+=1;w['completion_deadline_ms']+=10000
        if rec['case']=='no_future_request':changed['task_stream']=[t for t in changed['task_stream'] if t['task_id']!='water'];changed['action_grounding']=[g for g in changed['action_grounding'] if g['task_id']!='water'];changed['home']['resources']['task_power_bounds_kw'].pop('water');changed['exogenous_events']=[]
        ck(rec['input']==changed and r['arm']==rec['arm'] and r['review_delay_ms']==0 and doc['source_config_id']==main['config']['config_id'] and doc['lock_sha256']==sha(B/'preregistration_lock_revision3.json'),'diagnostic complete independent counterfactual input '+str((i,key)))
        ck(pre(m)==pre(r) and obj(pre(r))==rec['prefix_sha256'] and rec['cutoff_ms']==cutoff and rec['performance_sample'] is False,'diagnostic complete prefix '+str((i,key)))
        diag.append({'config_id':main['config']['config_id'],'arm':key[0],'case':key[1],'prefix_equal':True})
    ck(seen=={(arm,case) for arm in ('retain','replan') for case in ('different_arrival','different_request','no_future_request')},'six exact diagnostics '+str(i))
ck(diag==stat['information_checks'] and len(diag)==24,'24 diagnostics isolated exact identities')
for primary,sensitive in zip(details[::2],details[1::2]):
    a=primary['independent_pair'];b=sensitive['independent_pair'];ck(a['per_task_deltas']==b['per_task_deltas'] and a['metrics']==b['metrics'] and a['whole_house']==b['whole_house'],primary['config_id']+' common100ms same arm differences')
    tight=primary['capacity_arm']=='competition'
    for armidx in range(2):
        pa=a['audits'][armidx];pb=b['audits'][armidx]
        ck(pa['denominators']=={'required':4,'completed':4,'timely':3 if tight else 4} and pa['subsets']['early']['timely']==3 and pa['tasks']['water']['timely']==(not tight),primary['config_id']+f' arm{armidx} real service and lateness separated')
        ck(all(pb['tasks'][tid][m]-pa['tasks'][tid][m]==(100 if not tight and tid=='water' else 0) for tid in pa['required_task_ids'] for m in ('start_ms','completion_ms')),primary['config_id']+f' arm{armidx} common delay only actual affected start finish')
sys.path.insert(0,str(R));from homecoord_bench.task_revision import f2_reservation_ablation_v1 as author
author.run_event_simulation=lambda *a,**k:(_ for _ in ()).throw(AssertionError('new simulations forbidden'))
ck(eq(author.statistics(),stat),'saved whole statistics reproduction without simulator after independent replay')
out={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'configurations':details,'fresh_baselines':baseline,'information_diagnostics':diag,'reviewed_sha256':{p:sha(R/p) for p in verification['artifact_sha256']},'actual_tests':read(O/'F2_RESERVATION_ABLATION_V1_TESTS_20261005.json'),'new_simulations':0,'api_calls':0}
(O/'F2_RESERVATION_ABLATION_V1_AUDIT_20261005.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'checks':len(checks),'errors':out['errors'],'pairs':[{'config':d['config_id'],'water_delta':d['independent_pair']['per_task_deltas']['water']['completion_ms'],'response_mean_delta':d['independent_pair']['common_K_time']['metrics']['completion_latency_ms']['effects']['right_minus_left'],'house_delta':d['independent_pair']['whole_house']['right_minus_left']} for d in details]},ensure_ascii=False))
