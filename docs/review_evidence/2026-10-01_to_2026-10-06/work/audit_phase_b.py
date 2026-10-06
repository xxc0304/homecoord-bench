import json, hashlib, copy, csv
from pathlib import Path
REPO=Path(r'.')
BASE=REPO/'docs/implementation_review_20261001'
OUT=Path('outputs'); OUT.mkdir(exist_ok=True)
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=read(BASE/'manifest.json'); index=read(BASE/'index.json')
hash_errors=[]
for field in ['source_sha256','artifact_sha256','historical_result_sha256']:
    for path,h in manifest[field].items():
        if sha(REPO/path)!=h: hash_errors.append([field,path])
contracts=read(REPO/'docs/design_review_20261001/contracts.json')
contract_rows={r['contract']['episode_id']:r for r in contracts['rows']}
def get(state,path):
    for k in path.split('.'):
        if not isinstance(state,dict):return None
        state=state.get(k)
    return state
def put(state,path,value):
    parts=path.split('.')
    for k in parts[:-1]:state=state.setdefault(k,{})
    state[parts[-1]]=copy.deepcopy(value)
def holds(state,c):
    a,b=get(state,c['path']),c['value'];op=c['op']
    if op=='eq':return a==b
    if op=='neq':return a!=b
    if a is None:return False
    return {'lt':lambda:a<b,'lte':lambda:a<=b,'gt':lambda:a>b,'gte':lambda:a>=b,'between':lambda:b[0]<=a<=b[1]}[op]()
def valid(state,rules):
    return all(not all(holds(state,x) for x in r.get('when',[])) or all(holds(state,x) for x in r.get('must',[])) for r in rules)
def match(event,task):
    return any(all(event.get(k)==v for k,v in spec.items()) for spec in task.get('acceptable_actions',[task.get('required_action',{})]))
details=[];rows=[];all_errors=[];event_types=set()
for entry in index['entries']:
    packet=read(REPO/entry['path']);ep=packet['episode'];eid=ep['episode_id']
    raw_hash=hashlib.sha256(json.dumps(ep,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if raw_hash!=contract_rows[eid]['source_episode_sha256']:hash_errors.append(['source_episode',eid])
    for ri,run in enumerate(packet['runs']):
        errors=[];events=run['trace']['events'];r=run['reported_result']
        tasks={t['task_id']:t for t in ep['task_stream']};agents={a['agent_id']:a for a in ep['agents']}
        state=copy.deepcopy(ep['initial_state']['values']);version=ep['initial_state']['version'];clock=ep['episode_release_at_ms']
        active={};receipts={};starts={};finishes={};intervals=[];capacity_peak=0;harm=0;violations=0;first_goal=None
        prestates={};release_events={};reservation={};evidence=[]
        def check(ok,msg):
            if not ok:errors.append(msg)
        for ei,x in enumerate(events):
            event_types.add(x['type']);now=x['timestamp_ms'];kind=x['type'];tid=x.get('task_id');pid=x.get('proposal_id')
            check(now>=clock,f'events[{ei}]: clock reversal')
            if not valid(state,ep['constraints']):harm+=now-clock
            clock=now
            if kind=='task_released':
                check(now==tasks[tid]['release_at_ms'],f'events[{ei}]: wrong release')
                release_events[x['request_id']]=(ei,copy.deepcopy(state),version,now)
            if kind=='action_reserved':reservation[pid]=x
            if kind=='state_update':
                if x.get('source')=='action_started':
                    prestates[tid]=copy.deepcopy(state)
                    candidates=[g for g in ep['action_grounding'] if g['task_id']==tid and g.get('start_effects',{})==x['patch']]
                    check(bool(candidates),f'events[{ei}]: invalid start patch')
                else:
                    check(any(ev['at_ms']==now and ev['patch']==x['patch'] for ev in ep['exogenous_events']),f'events[{ei}]: undocumented external patch')
                for path,value in x['patch'].items():put(state,path,value)
                version+=1;check(version==x['new_state_version'],f'events[{ei}]: wrong version')
            if kind in ['dependency_waiting','dependency_ready','action_rejected','state_update']:
                evidence.append({'event_index':ei,'timestamp_ms':now,'type':kind,'task_id':tid,'reason':x.get('reason'),'source':x.get('source')})
            if kind=='dependency_ready':
                check(all(d in receipts for d in tasks[tid].get('depends_on',[])),f'events[{ei}]: early dependency ready')
            if kind=='action_started':
                t=tasks[tid];g=next(g for g in ep['action_grounding'] if (g['task_id'],g['target'],g['operation'])==(tid,x['target'],x['operation']))
                check(x['agent_id']==t['agent_id'],f'events[{ei}]: wrong agent')
                check(now>=t['release_at_ms'],f'events[{ei}]: early start')
                check(pid not in active,f'events[{ei}]: duplicate active proposal')
                check(x['duration_ms']==g['duration_ms'] and x['power_kw']==g['power_kw'],f'events[{ei}]: cost mismatch')
                check(x['start_effects']==g.get('start_effects',{}) and x['completion_effects']==g.get('completion_effects',g.get('effects',{})),f'events[{ei}]: effects mismatch')
                tools=[z for z in ep['tool_catalog'] if (z['agent_id'],z['target'],z['operation'])==(x['agent_id'],x['target'],x['operation'])]
                check(len(tools)==1 and tools[0]['tool_name'] in agents[x['agent_id']]['tools'],f'events[{ei}]: unauthorized')
                check('devices.'+x['target'] in agents[x['agent_id']]['writable_resources'],f'events[{ei}]: target not writable')
                required=tools[0]['preconditions']
                check(all(any(all(q.get(k)==v for k,v in req.items()) for q in x['requires']) for req in required),f'events[{ei}]: missing required predicate')
                before=prestates.pop(tid,state)
                check(all(holds(before,q) for q in x['requires']),f'events[{ei}]: failed start precondition')
                check(all(d in receipts for d in t.get('depends_on',[])),f'events[{ei}]: missing actual predecessor receipt')
                check(pid in reservation and now==reservation[pid]['scheduled_start_ms'],f'events[{ei}]: unreserved or mis-timed start')
                check(now>=reservation[pid]['timestamp_ms']+ep['simulation']['command_latency_ms'],f'events[{ei}]: missing command delay')
                active[pid]=(ei,x,g)
                load=sum(v[1]['power_kw'] for v in active.values());capacity_peak=max(capacity_peak,load)
                check(load<=ep['home']['resources']['max_power_kw'],f'events[{ei}]: over capacity')
                if match(x,t):starts.setdefault(tid,(ei,now))
                evidence.append({'event_index':ei,'timestamp_ms':now,'type':kind,'task_id':tid,'proposal_id':pid,'active_resource_units':load})
            if kind=='action_completed':
                check(pid in active,f'events[{ei}]: completion without start')
                si,s,g=active.pop(pid)
                check(all(x[k]==s[k] for k in ['task_id','agent_id','target','operation']),f'events[{ei}]: completion identity mismatch')
                check(now==s['timestamp_ms']+g['duration_ms'],f'events[{ei}]: premature or delayed completion')
                check(x['effects']==g.get('completion_effects',g.get('effects',{})),f'events[{ei}]: wrong completion effects')
                for path,value in x['effects'].items():put(state,path,value)
                version+=1;check(version==x['new_state_version'],f'events[{ei}]: wrong completion version')
                if match(x,tasks[tid]):
                    finishes.setdefault(tid,(ei,now));receipts[tid]=(ei,now)
                intervals.append({'task_id':tid,'proposal_id':pid,'start_event':si,'finish_event':ei,'start_ms':s['timestamp_ms'],'finish_ms':now,'units':s['power_kw']})
                evidence.append({'event_index':ei,'timestamp_ms':now,'type':kind,'task_id':tid,'proposal_id':pid})
            if all(holds(state,g) for g in ep['goals']) and first_goal is None:first_goal=now
        check(not active,'active work missing completion')
        check(state==run['trace']['final_state'] and version==run['trace']['final_state_version'],'final state or version mismatch')
        check(run['trace']['agent_requests']==[z['request'] for z in run['calls']],'request capture mismatch')
        proposals={}
        for ci,call in enumerate(run['calls']):
            req=call['request'];tid=req['task']['task_id'];agent=agents[tasks[tid]['agent_id']]
            check(req['current_time_ms']>=tasks[tid]['release_at_ms'],f'calls[{ci}]: before release')
            check(req['agent']==agent and req['allowed_tools']==agent['tools'],f'calls[{ci}]: permission mismatch')
            check(req['available_actions']==[z for z in ep['tool_catalog'] if z['agent_id']==agent['agent_id']],f'calls[{ci}]: tool catalog mismatch')
            _,ss,v,at=release_events[req['request_id']]
            check(req['state_version']==v and req['current_time_ms']==at,f'calls[{ci}]: release snapshot mismatch')
            def leaves(obj,p=''):
                for k,val in obj.items():
                    q=f'{p}.{k}' if p else k
                    if isinstance(val,dict):yield from leaves(val,q)
                    else:yield q,val
            for path,val in leaves(req['state']):
                check(get(ss,path)==val,f'calls[{ci}]: incorrect visible state {path}')
                check(any(q=='*' or path==q or path.startswith(q+'.') for q in agent['observable_state']+agent['writable_resources']),f'calls[{ci}]: unauthorized visible path {path}')
            if eid.startswith('D-F1-'):check(not {'action_template','required_action','acceptable_actions'}&req['task'].keys(),f'calls[{ci}]: scoring hint leaked')
            returns=[x for x in events if x['type']=='proposal_returned' and x['request_id']==req['request_id']]
            check(len(returns)==1 and returns[0]['timestamp_ms']==at+call['logical_latency_ms'],f'calls[{ci}]: logical return time')
            for action in call['decision']['actions']:
                check(action['proposal_id'] not in proposals,f'calls[{ci}]: duplicate proposal identity')
                check(action['based_on_state_version']==req['state_version'],f'calls[{ci}]: incorrect proposal snapshot version')
                check(action['parameters']==[],f'calls[{ci}]: unsupported parameters in these parameterless tools')
                proposals[action['proposal_id']]=(tid,agent['agent_id'],action)
        for ei,x in enumerate(events):
            if x['type'] in ['action_started','action_completed']:
                check(x['proposal_id'] in proposals,f'events[{ei}]: action not from captured proposal')
                tid,agent,action=proposals[x['proposal_id']]
                check((x['task_id'],x['agent_id'],x['target'],x['operation'])==(tid,agent,action['target'],action['operation']),f'events[{ei}]: proposal identity mismatch')
        completed={tid:tid in finishes for tid in tasks};started={tid:tid in starts for tid in tasks}
        wait={tid:starts[tid][1]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()}
        latency={tid:finishes[tid][1]-t['release_at_ms'] if tid in finishes else None for tid,t in tasks.items()}
        tardy={tid:max(0,finishes[tid][1]-t['completion_deadline_ms']) if tid in finishes else None for tid,t in tasks.items()}
        deadline={tid:tid in finishes and finishes[tid][1]<=t['completion_deadline_ms'] for tid,t in tasks.items()}
        expected={'task_correct_action_started':started,'task_correct_action_completed':completed,'task_start_wait_ms':wait,'task_completion_latency_ms':latency,'task_completion_tardiness_ms':tardy,'task_service':completed,'served_task_count':sum(completed.values()),'serviceable_task_count':len(tasks),'task_service_rate':sum(completed.values())/len(tasks),'task_deadline_met':deadline,'all_deadlines_met':all(deadline.values()),'task_unstarted_count':sum(not x for x in started.values()),'task_incomplete_count':sum(not x for x in completed.values()),'max_observed_task_start_wait_ms':max((x for x in wait.values() if x is not None),default=None),'task_start_within_1s':{tid:w is not None and w<=1000 for tid,w in wait.items()},'task_action_finish_time_ms':{tid:finishes[tid][1]-ep['episode_release_at_ms'] if tid in finishes else None for tid in tasks},'task_completion_time_ms':None if first_goal is None else first_goal-ep['episode_release_at_ms'],'final_goal_success':all(holds(state,g) for g in ep['goals']),'state_constraint_violation_duration_ms':harm,'accepted_action_count':sum(x['type']=='action_started' for x in events),'rejected_action_count':sum(x['type']=='action_rejected' for x in events)}
        expected['process_valid_success']=expected['final_goal_success'] and harm==0
        expected['timely_process_valid_success']=expected['process_valid_success'] and all(deadline.values())
        for key,value in expected.items():check(r[key]==value,f'reported_result.{key}: {r[key]} != {value}')
        check(r['conflict_counts']['C3']==0,'reported capacity conflicts')
        if eid.startswith('DEP-'):
            check(r['dependency_completed_receipts']==sorted(receipts),'dependency receipt summary mismatch')
            check(run['dependency_metrics']['completed']==completed,'dependency metric completion mismatch')
            check(run['dependency_metrics']['predecessor_completion_receipts_ms']=={k:v[1] for k,v in receipts.items()},'dependency receipt timestamps mismatch')
        detail={'episode_id':eid,'run_index':ri,'policy':run['policy'],'arrival_order_index':run['arrival_order_index'],'errors':errors,'capacity':ep['home']['resources']['max_power_kw'],'peak_actual_units':capacity_peak,'intervals':intervals,'metrics':expected,'evidence':evidence}
        details.append(detail);all_errors.extend({'episode_id':eid,'run_index':ri,'error':x} for x in errors)
        rows.append({'episode_id':eid,'run_index':ri,'policy':run['policy'],'arrival_order_index':run['arrival_order_index'],'error_count':len(errors),'capacity':detail['capacity'],'peak_actual_units':capacity_peak,'completed':sum(completed.values()),'tasks':len(tasks),'late_completed':sum(x is not None and x>0 for x in tardy.values()),'incomplete':expected['task_incomplete_count'],'all_deadlines_met':expected['all_deadlines_met']})
historical_errors=[]
f1_history=read(REPO/'homecoord_bench/results/task_family_development_20260930.json')
dep_history=read(REPO/'homecoord_bench/results/dependency_v3_offline_20261001.json')
for entry in index['entries']:
    packet=read(REPO/entry['path']);eid=entry['episode_id']
    for ri,run in enumerate(packet['runs']):
        if eid.startswith('D-F1-'):
            old=next(x for x in f1_history['rows'] if (x['episode_id'],x['policy'],x['arrival_order_index'])==(eid,run['policy'],run['arrival_order_index']))
            rr=run['reported_result']
            checks={k:rr[k] for k in ['task_start_wait_ms','task_completion_latency_ms','all_deadlines_met']}
            checks.update(all_tasks_served=all(rr['task_correct_action_completed'].values()),process_violation_ms=rr['state_constraint_violation_duration_ms'])
            for key,value in checks.items():
                if old[key]!=value:historical_errors.append([eid,ri,key])
        else:
            old=next(x for x in dep_history['runs'] if x['episode_id']==eid and x['policy']==run['policy'] and x['dependencies_enabled'])
            if old['metrics']!=run['dependency_metrics']:historical_errors.append([eid,ri,'metrics'])
            if old['trace']!={k:run['trace'][k] for k in old['trace']}:historical_errors.append([eid,ri,'saved trace'])
summary={'phase':'B_single_reviewer','manifest_sha256':sha(BASE/'manifest.json'),'configurations':len(index['entries']),'runs':len(details),'hash_errors':hash_errors,'audit_errors':all_errors,'historical_errors':historical_errors,'event_types':sorted(event_types),'scope':'Static source review plus independent ordered JSON event replay. No simulator rerun, model or network call. Historical JSON containers loaded but comparisons restricted to the authorized 13 configurations.','runs_summary':rows}
(OUT/'PHASE_B_EVENT_AUDIT.json').write_text(json.dumps({'summary':summary,'runs':details},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (OUT/'PHASE_B_RUN_CHECKS.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    w=csv.DictWriter(stream,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
print(json.dumps({'manifest_sha256':summary['manifest_sha256'],'hash_errors':hash_errors,'audit_errors':all_errors,'runs':len(details),'groups':[{ 'episode_id':e['episode_id'],'runs':sum(x['episode_id']==e['episode_id'] for x in rows),'peak_actual_units':max(x['peak_actual_units'] for x in rows if x['episode_id']==e['episode_id']),'late_task_instances':sum(x['late_completed'] for x in rows if x['episode_id']==e['episode_id']),'incomplete_task_instances':sum(x['incomplete'] for x in rows if x['episode_id']==e['episode_id'])} for e in index['entries']]},ensure_ascii=False,indent=2))
