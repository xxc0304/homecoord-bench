import json,hashlib,copy,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(r'.');B=ROOT/'homecoord_bench/task_revision/fixtures/f2_v7';O=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def get(s,p):
    for k in p.split('.'):s=s.get(k) if isinstance(s,dict) else None
    return s
def put(s,p,v):
    ks=p.split('.')
    for k in ks[:-1]:s=s.setdefault(k,{})
    s[ks[-1]]=copy.deepcopy(v)
def holds(s,c):return get(s,c['path'])==c['value'] if c['op']=='eq' else get(s,c['path'])!=c['value']
eps={e['episode_id']:e for e in read(B/'inputs.json')['episodes']};idx=read(B/'index.json');manifest=read(B/'manifest.json');hash_errors=[]
for section in ('source_sha256','artifact_sha256'):
    for p,h in manifest[section].items():
        if sha(ROOT/p)!=h:hash_errors.append(p)
main={p:read(ROOT/p) for p in idx['run_files']};diag={p:read(ROOT/p) for p in idx['diagnostic_files']}
GOAL='Complete the requested service using the authorized prepare operation before its deadline; once started, finish the nonpreemptive cycle.'
def pt(t,d):return {'task_id':t['task_id'],'agent_id':d['agent_id'],'release_at_ms':t['release_at_ms'],'completion_deadline_ms':t['completion_deadline_ms'],'priority':t['priority'],'requested_service':d['service'],'goal':GOAL}
def expected_input(e,task,policy,state,version):
    ds={d['agent_id']:d for d in e['public_devices']};d=ds[task['agent_id']];path='devices.'+d['target'];released=[t for t in e['task_stream'] if t['release_at_ms']<=task['release_at_ms']]
    tools=[{'agent_id':d['agent_id'],'tool_name':d['role']+'_'+op,'target':d['target'],'operation':op,'parameters':[],'preconditions':[{'path':path,'op':'eq','value':'idle'}],'provides_service':d['service'] if op=='prepare' else 'none','cost_contract':{'duration_ms':duration,'resource_units':units},'description':'Static authorized operation; availability does not imply a request exists.'} for op,duration,units in [('prepare',d['duration_ms'],d['resource_units']),('off',100,0)]]
    ag={'agent_id':d['agent_id'],'role':d['role'],'tools':[x['tool_name'] for x in tools],'observable_state':[path,'coordination_context'],'writable_resources':[path],'goal_visibility':'released','constraint_visibility':'public'}
    return {'request_id':'F2-public-home:'+policy+':'+task['task_id'],'episode_id':'F2-public-home','base_episode_id':'F2-public-home','architecture':policy,'current_time_ms':task['release_at_ms'],'state_version':version,'agent':ag,'task':pt(task,d),'state':{'devices':{d['target']:get(state,path)},'coordination_context':{'resource_capacity_units':e['home']['resources']['max_power_kw'],'objective':'complete released services within their own deadlines','requests':[pt(t,ds[t['agent_id']]) for t in released],'static_devices':e['public_devices']}},'goals':[{'path':'devices.'+ds[t['agent_id']]['target'],'op':'eq','value':'complete'} for t in released],'constraints':[],'allowed_tools':ag['tools'],'available_actions':tools,'pending_proposals':[]}
def audit(e,r,file,ri,section):
    errors=[];ev=r['trace']['events'];res=r['result'];tasks={t['task_id']:t for t in e['task_stream']};agents={a['agent_id']:a for a in e['agents']};state=copy.deepcopy(e['initial_state']['values']);ver=e['initial_state']['version'];clock=0;starts={};done={};active={};release={};pre={};reserved={};intervals=[];evidence=[];peak=0;first_goal=None
    def check(ok,msg):
        if not ok:errors.append(msg)
    for j,x in enumerate(ev):
        at=x['timestamp_ms'];kind=x['type'];tid=x.get('task_id');pid=x.get('proposal_id');check(at>=clock,f'e{j} time order');clock=at
        if kind=='task_released':
            check(at==tasks[tid]['release_at_ms'],f'e{j} release');release[tid]=(copy.deepcopy(state),ver,j)
        if kind=='action_reserved':reserved[pid]=x
        if kind=='state_update':
            if x.get('source')=='action_started':
                pre[tid]=copy.deepcopy(state)
                check(any(g['task_id']==tid and g['start_effects']==x['patch'] for g in e['action_grounding']),f'e{j} start effect')
            else:check(any(z['at_ms']==at and z['patch']==x['patch'] for z in e['exogenous_events']),f'e{j} undeclared external event')
            for p,v in x['patch'].items():put(state,p,v)
            ver+=1;check(ver==x['new_state_version'],f'e{j} version')
        if kind=='action_started':
            task=tasks[tid];g=next(g for g in e['action_grounding'] if (g['task_id'],g['target'],g['operation'])==(tid,x['target'],x['operation']));ag=agents[task['agent_id']];tool=next(z for z in e['tool_catalog'] if (z['agent_id'],z['target'],z['operation'])==(x['agent_id'],x['target'],x['operation']))
            check(x['operation']=='prepare' and x['agent_id']==task['agent_id'] and at>=task['release_at_ms'],f'e{j} identity/release/service')
            check(tool['tool_name'] in ag['tools'] and 'devices.'+x['target'] in ag['writable_resources'],f'e{j} authorization')
            ss=pre.pop(tid,state);check(all(holds(ss,c) for c in x['requires']) and all(holds(ss,c) for c in tool['preconditions']),f'e{j} start prerequisite')
            check(x['state_version_at_start']==ver,f'e{j} start version')
            check(x['duration_ms']==g['duration_ms'] and x['power_kw']==g['power_kw'] and x['start_effects']==g['start_effects'] and x['completion_effects']==g['completion_effects'],f'e{j} execution contract')
            check(pid in reserved and at==reserved[pid]['scheduled_start_ms'] and at>=reserved[pid]['timestamp_ms']+100,f'e{j} reservation delay')
            active[pid]=(j,x,g);starts.setdefault(tid,(j,at));load=sum(v[1]['power_kw'] for v in active.values());peak=max(peak,load);check(load<=e['home']['resources']['max_power_kw'],f'e{j} capacity exceeded')
        if kind=='action_completed':
            check(pid in active,f'e{j} completion without start')
            sj,s,g=active.pop(pid);check(all(x[k]==s[k] for k in ('task_id','agent_id','target','operation')) and at==s['timestamp_ms']+g['duration_ms'] and x['effects']==g['completion_effects'],f'e{j} genuine completion')
            done.setdefault(tid,(j,at));intervals.append({'task_id':tid,'start_event':sj,'end_event':j,'start_ms':s['timestamp_ms'],'end_ms':at,'units':s['power_kw']})
            for p,v in x['effects'].items():put(state,p,v)
            ver+=1;check(ver==x['new_state_version'],f'e{j} completion version')
        if first_goal is None and all(holds(state,g) for g in e['goals']):first_goal=at
        evidence.append({'index':j,'type':kind,'time_ms':at,'task_id':tid,'reason':x.get('reason')})
    check(not active and state==r['trace']['final_state'] and ver==r['trace']['final_state_version'],'final state/version/nonpreemption')
    check(r['trace']['agent_requests']==[c['request'] for c in r['calls']],'provider/trace match')
    check(len(r['calls'])==len(tasks),'one actual call per released task')
    proposals={}
    for j,c in enumerate(r['calls']):
        q=c['request'];tid=q['task']['task_id'];ss,sv,ei=release[tid]
        check(q==expected_input(e,tasks[tid],r['policy'],ss,sv),f'calls[{j}] complete whitelist mismatch')
        ret=[x for x in ev if x['type']=='proposal_returned' and x['request_id']==q['request_id']];check(len(ret)==1 and ret[0]['timestamp_ms']==q['current_time_ms']+300,f'calls[{j}] return time')
        for p in c['decision']['actions']:proposals[p['proposal_id']]=(tid,p)
    for j,x in enumerate(ev):
        if x['type'] in ('action_started','action_completed'):
            check(x['proposal_id'] in proposals,f'e{j} no provider proposal');tid,p=proposals[x['proposal_id']]
            check((tid,p['target'],p['operation'])==(x['task_id'],x['target'],x['operation']),f'e{j} proposal identity')
    completed={tid:tid in done for tid in tasks};started={tid:tid in starts for tid in tasks};wait={tid:starts[tid][1]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()};lat={tid:done[tid][1]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()};late={tid:max(0,done[tid][1]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()};ontime={tid:tid in done and done[tid][1]<=t['completion_deadline_ms'] for tid,t in tasks.items()}
    m={'task_correct_action_started':started,'task_correct_action_completed':completed,'task_start_wait_ms':wait,'task_completion_latency_ms':lat,'task_completion_tardiness_ms':late,'task_deadline_met':ontime,'all_deadlines_met':all(ontime.values()),'task_service':completed,'served_task_count':sum(completed.values()),'serviceable_task_count':len(tasks),'task_service_rate':sum(completed.values())/len(tasks),'task_unstarted_count':sum(not v for v in started.values()),'task_incomplete_count':sum(not v for v in completed.values())}
    for k,v in m.items():check(res[k]==v,'result.'+k)
    for k,v in r['audit']['recount'].items():check(v==m[k],'author audit.'+k)
    check(res['conflict_counts']['C3']==0,'reported capacity conflicts')
    return {'section':section,'file':file,'run_index':ri,'episode_id':e['episode_id'],'policy':r['policy'],'errors':errors,'peak_units':peak,'capacity':e['home']['resources']['max_power_kw'],'intervals':intervals,'computed':m,'events':evidence,'release_event_indices':{tid:v[2] for tid,v in release.items()},'call_task_ids':[c['request']['task']['task_id'] for c in r['calls']]}
details=[]
for p,packet in main.items():
    e=eps[packet['evaluation_episode_id']]
    for i,r in enumerate(packet['runs']):details.append(audit(e,r,p,i,'main'))
prefixes=[]
for p,packet in diag.items():
    e=packet['episode'];stem=Path(p).name.replace('-'+packet['case']+'.json','.json');orig=next(v for path,v in main.items() if Path(path).name==stem)
    for i,r in enumerate(packet['runs']):
        details.append(audit(e,r,p,i,'counterfactual'));before=packet['before_ms'];b=orig['runs'][i]
        prefix=lambda z:{'calls':[c for c in z['calls'] if c['request']['current_time_ms']<before],'events':[x for x in z['trace']['events'] if x['timestamp_ms']<before]}
        prefixes.append({'file':p,'run_index':i,'policy':r['policy'],'case':packet['case'],'before_ms':before,'full_prefix_equal':prefix(r)==prefix(b),'call_indices':[j for j,c in enumerate(r['calls']) if c['request']['current_time_ms']<before],'event_indices':[j for j,x in enumerate(r['trace']['events']) if x['timestamp_ms']<before]})
out={'hash_errors':hash_errors,'configurations':8,'main_runs':32,'counterfactual_runs':48,'details':details,'prefix_checks':prefixes}
(O/'F2_V7_EVENT_AUDIT_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hash_errors':hash_errors,'rows':len(details),'audit_errors':[{'file':d['file'],'run':d['run_index'],'errors':d['errors']} for d in details if d['errors']],'prefix_equal':sum(p['full_prefix_equal'] for p in prefixes),'main':[{'id':d['episode_id'],'run':d['run_index'],'peak':d['peak_units'],'incomplete':d['computed']['task_incomplete_count'],'late':{k:v for k,v in d['computed']['task_completion_tardiness_ms'].items() if v},'intervals':d['intervals'],'releases':d['release_event_indices']} for d in details[:32]]},indent=2))
