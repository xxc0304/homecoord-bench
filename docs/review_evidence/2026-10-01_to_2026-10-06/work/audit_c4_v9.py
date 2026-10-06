import json,copy,hashlib
from pathlib import Path
R=Path(r'.');B=R/'homecoord_bench/task_revision/fixtures/c4_v9';O=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def get(s,p):
    for k in p.split('.'):s=s[k]
    return s
def put(s,p,v):
    ks=p.split('.')
    for k in ks[:-1]:s=s.setdefault(k,{})
    s[ks[-1]]=copy.deepcopy(v)
def holds(s,c):return get(s,c['path'])==c['value'] if c['op']=='eq' else get(s,c['path'])!=c['value']
def constraints(s,rs):return all(not all(holds(s,c) for c in r.get('when',[])) or all(holds(s,c) for c in r['must']) for r in rs)
main=read(B/'inputs.json')['episodes'];diagnostics=read(B/'diagnostic_inputs.json')['cases'];eps={e['episode_id']:e for e in main+[x['episode'] for x in diagnostics]};idx=read(B/'index.json');manifest=read(B/'manifest.json');hash_errors=[]
for section in ('source_sha256','artifact_sha256'):
    for p,h in manifest[section].items():
        if sha(R/p)!=h:hash_errors.append(p)
def expected_input(e,t,policy,ss,version):
    agent=copy.deepcopy(next(a for a in e['agents'] if a['agent_id']==t['agent_id']));agent.update(goal_visibility='local',constraint_visibility='local',policy_constraints=[])
    st={}
    for p in agent['observable_state']+agent['writable_resources']:put(st,p,get(ss,p))
    task={k:t[k] for k in ('task_id','agent_id','release_at_ms','completion_deadline_ms','priority') if k in t};task['goal']='Perform the declared service. Trusted local policy stops on invalidity; cleaning may restart from zero, irrigation cancellation is terminal for this request.'
    tools=[{k:z[k] for k in ('agent_id','tool_name','target','operation','parameters','preconditions','cost_contract')} for z in e['tool_catalog'] if z['agent_id']==agent['agent_id']];scene='HC-M16' if e['c4_scene']=='CLEAN' else 'HC-M17'
    return {'request_id':scene+':'+policy+':'+t['task_id'],'episode_id':scene,'base_episode_id':scene,'architecture':policy,'current_time_ms':t['release_at_ms'],'state_version':version,'state':st,'agent':agent,'task':task,'goals':[],'constraints':[],'allowed_tools':agent['tools'],'available_actions':tools,'pending_proposals':[]}
def audit(e,r,file,ri,section):
    errors=[];contract_errors=[];events=r['trace']['events'];res=r['result'];tasks={t['task_id']:t for t in e['task_stream']};cs=e['simulation']['lifecycle_contracts'];primary=e['task_stream'][0]['task_id'];signal=cs[primary]['valid_when'][0]['path'];state=copy.deepcopy(e['initial_state']['values']);ver=e['initial_state']['version'];clock=0;harm=0;peak=0
    active={};all_starts={};starts={};done={};physical={};cancelled=set();withdrawn={};expected_withdrawn=set();requests={};onsets={};exposures={};refs={};extras={};terminated={};intervals=[];snap={};pre={};reservation={};phases=[];evidence=[];restarts={};invalid_attempts=set()
    def ck(ok,s):
        if not ok:errors.append(s)
    def valid(tid):return all(holds(state,c) for c in cs[tid]['valid_when'])
    for j,x in enumerate(events):
        now=x['timestamp_ms'];kind=x['type'];tid=x.get('task_id');pid=x.get('proposal_id');ck(now>=clock,f'e{j} time order')
        if not constraints(state,e['constraints']):harm+=now-clock
        for q,s in active.items():
            if s['task_id'] in cs and not valid(s['task_id']) and now>clock:
                onset=onsets[q];exposures[q]=exposures.get(q,0)+now-clock;refs[q]=refs.get(q,0)+max(0,min(now,onset+200)-clock);extras[q]=extras.get(q,0)+max(0,now-max(clock,onset+200))
        clock=now
        if kind=='task_released':ck(now==tasks[tid]['release_at_ms'],f'e{j} publication');snap[tid]=(copy.deepcopy(state),ver)
        if kind=='action_reserved':reservation[pid]=x
        if kind=='task_withdrawn':ck(tid not in withdrawn and cs[tid]['mode']=='withdraw',f'e{j} withdrawal');withdrawn[tid]=now
        if kind=='state_update' and x['source'] not in ('action_started','stop_ack'):
            if x['patch'].get(signal) is True:
                live=next((s for s in active.values() if s['task_id']==primary),None)
                if live and now==live['timestamp_ms']+live['duration_ms']:stage='natural_completion_boundary'
                elif primary in done:stage='after_service_completion'
                elif live:
                    f=(now-live['timestamp_ms'])/live['duration_ms'];stage='running_early' if f<1/3 else 'running_mid' if f<2/3 else 'running_late'
                else:stage='before_release' if now<tasks[primary]['release_at_ms'] else 'released_not_started'
                phases.append({'event_index':j,'timestamp_ms':now,'actual_stage':stage,'nominal_window':e['nominal_window']})
            elif x['source']=='challenge_unrelated':phases.append({'event_index':j,'timestamp_ms':now,'actual_stage':'unrelated_update','nominal_window':e['nominal_window']})
        if kind=='state_update':
            source=x['source'];patch=x['patch']
            if source=='action_started':pre[tid]=copy.deepcopy(state);ck(any(g['task_id']==tid and g['start_effects']==patch for g in e['action_grounding']),f'e{j} start effects')
            elif source=='stop_ack':ck(patch==cs[tid]['stop_effects'] and pid in requests and now==requests[pid]['ack_due_ms'],f'e{j} stop effects/timing')
            else:ck(any(v['at_ms']==now and v['patch']==patch for v in e['exogenous_events']),f'e{j} world effects')
            for p,v in patch.items():put(state,p,v)
            ver+=1;ck(ver==x['new_state_version'],f'e{j} state version')
        if kind=='action_started':
            g=next(g for g in e['action_grounding'] if g['task_id']==tid);tool=next(z for z in e['tool_catalog'] if z['agent_id']==x['agent_id']);agent=next(a for a in e['agents'] if a['agent_id']==x['agent_id']);before=pre.pop(tid,state)
            ck(tid not in withdrawn and now>=tasks[tid]['release_at_ms'] and pid not in active,f'e{j} closed/early start')
            ck((x['agent_id'],x['target'],x['operation'],x['duration_ms'],x['power_kw'])==(g['agent_id'],g['target'],g['operation'],g['duration_ms'],g['power_kw']),f'e{j} identity/cost')
            ck(x['start_effects']==g['start_effects'] and x['completion_effects']==g['completion_effects'] and all(holds(before,c) for c in x['requires']) and all(holds(before,c) for c in tool['preconditions']),f'e{j} prerequisites/effects')
            ck(tool['tool_name'] in agent['tools'] and 'devices.'+x['target'] in agent['writable_resources'] and x['state_version_at_start']==ver,f'e{j} permissions/version')
            ck(pid in reservation and now==reservation[pid]['scheduled_start_ms'] and now>=reservation[pid]['timestamp_ms']+100,f'e{j} command/reservation')
            active[pid]=x;all_starts[pid]=x;starts.setdefault(tid,now);peak=max(peak,sum(s['power_kw'] for s in active.values()));ck(peak<=e['home']['resources']['max_power_kw'],f'e{j} capacity')
        if kind=='stop_requested':ck(pid in active and pid in onsets and now==onsets[pid] and x['ack_due_ms']==now+cs[tid]['stop_ack_delay_ms'] and pid not in requests,f'e{j} stop request');requests[pid]=x
        if kind=='restart_proposed':ck(tid not in withdrawn and x['additional_model_calls']==0 and valid(tid),f'e{j} restart');restarts[pid]=x
        if kind in ('action_stopped','action_completed','withdrawn_action_physically_completed'):
            ck(pid in active,f'e{j} unmatched termination');s=active.pop(pid);g=next(g for g in e['action_grounding'] if g['task_id']==tid);ck(s['task_id']==tid,f'e{j} termination identity')
            if kind=='action_stopped':ck(now==requests[pid]['ack_due_ms'] and x['actual_runtime_ms']==now-s['timestamp_ms'],f'e{j} actual stop');cancelled.add(pid)
            else:
                ck(all(x[k]==s[k] for k in ('agent_id','target','operation')) and now==s['timestamp_ms']+g['duration_ms'],f'e{j} natural finish')
                effects=g['completion_effects']
                if kind=='withdrawn_action_physically_completed':ck(tid in withdrawn,f'e{j} withdrawn physical end');effects={p:v for p,v in effects.items() if not p.startswith('service.')};physical[pid]={'task_id':tid,'proposal_id':pid,'timestamp_ms':now}
                else:
                    ck(tid not in withdrawn and pid not in cancelled,f'e{j} forbidden service receipt')
                    if pid in invalid_attempts and tid in cs and cs[tid]['mode']=='restart_from_zero':contract_errors.append({'event_index':j,'task_id':tid,'time_ms':now,'issue':'invalidated_clean_attempt_counted_as_service_completion'})
                    else:done[tid]=now
                ck(x['effects']==effects,f'e{j} completion effects')
                for p,v in x['effects'].items():put(state,p,v)
                ver+=1;ck(ver==x['new_state_version'],f'e{j} completion version')
            terminated[pid]={'timestamp_ms':now,'reason':kind};intervals.append({'task_id':tid,'proposal_id':pid,'start_ms':s['timestamp_ms'],'end_ms':now,'units':s['power_kw']})
        if kind=='completion_discarded':ck(pid in cancelled and now==all_starts[pid]['timestamp_ms']+all_starts[pid]['duration_ms'],f'e{j} cancelled receipt not discarded')
        if kind=='stop_ack_too_late':ck(pid not in active and pid in terminated and now==requests[pid]['ack_due_ms'],f'e{j} fictitious stop confirmation')
        for q,s in active.items():
            if s['task_id'] in cs and not valid(s['task_id']) and now<s['timestamp_ms']+s['duration_ms']:onsets.setdefault(q,now);invalid_attempts.add(q)
        for ct,c in cs.items():
            live=next((s for s in active.values() if s['task_id']==ct),None);at_boundary=live and now>=live['timestamp_ms']+live['duration_ms']
            if c['mode']=='withdraw' and now>=tasks[ct]['release_at_ms'] and ct not in done and not at_boundary and not valid(ct):expected_withdrawn.add(ct)
        evidence.append({'index':j,'type':kind,'time_ms':now,'task_id':tid,'proposal_id':pid,'reason':x.get('reason'),'source':x.get('source')})
    ck(not active and state==r['trace']['final_state'] and ver==r['trace']['final_state_version'],'final state/version')
    ck(set(withdrawn)==expected_withdrawn==set(res['withdrawn_task_ids']),'withdrawal legality')
    ck(harm==res['state_constraint_violation_duration_ms'],'harm duration')
    ck(r['trace']['agent_requests']==[c['request'] for c in r['calls']] and len(r['calls'])==len(tasks),'actual calls/trace/new identity')
    for j,call in enumerate(r['calls']):
        q=call['request'];tid=q['task']['task_id'];ss,sv=snap[tid];ck(q==expected_input(e,tasks[tid],r['policy'],ss,sv),f'q{j} full input contract')
        ret=[v for v in events if v['type']=='proposal_returned' and v['request_id']==q['request_id']];ck(len(ret)==1 and ret[0]['timestamp_ms']==q['current_time_ms']+r['declared_proposal_latency_ms'],f'q{j} latency')
    metrics={'task_correct_action_started':{tid:tid in starts for tid in tasks},'task_correct_action_completed':{tid:tid in done for tid in tasks},'task_start_wait_ms':{tid:starts[tid]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()},'task_completion_latency_ms':{tid:done[tid]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()},'task_completion_tardiness_ms':{tid:max(0,done[tid]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()},'task_deadline_met':{tid:tid in done and done[tid]<=t['completion_deadline_ms'] for tid,t in tasks.items()}}
    for k,v in metrics.items():ck(res[k]==v,'result.'+k)
    ck(res['all_deadlines_met']==all(metrics['task_deadline_met'].values()),'all deadlines')
    responses=[]
    for q,onset in onsets.items():
        end=terminated[q];request=requests.get(q);lat=request['timestamp_ms']-onset if request else None
        responses.append({'proposal_id':q,'invalidity_observed_ms':onset,'stop_request_latency_ms':lat,'stop_confirmed':end['reason']=='action_stopped','quiescence_latency_ms':end['timestamp_ms']-onset,'termination_reason':end['reason'],'request_timely':lat is not None and lat<=0,'quiescence_timely':end['timestamp_ms']-onset<=200,'actual_invalid_running_exposure_ms':exposures.get(q,0),'reference_ack_window_exposure_ms':refs.get(q,0),'extra_exposure_beyond_tolerance_ms':extras.get(q,0)})
    waiting={tid for tid in cs if cs[tid]['mode']=='restart_from_zero' and tid not in done and not valid(tid)}
    statuses={tid:'withdrawn' if tid in withdrawn else 'completed' if tid in done else 'pending_validity' if tid in waiting else 'unresolved' for tid in tasks}
    computed={'actual_event_stages':phases or [{'actual_stage':'no_event'}],'service_recount':{k:v for k,v in metrics.items() if k!='task_correct_action_started'},'request_disposition':statuses,'valid_withdrawal_by_task':{tid:tid in expected_withdrawn for tid,c in cs.items() if c['mode']=='withdraw'},'physical_completions_after_withdrawal':list(physical.values()),'response_records':responses,'harm_duration_ms':harm,'zero_harm':harm==0,'execution_intervals':intervals}
    for k,v in computed.items():ck(r['audit'][k]==v,'author audit.'+k)
    ck(set(res['waiting_recovery_task_ids'])==waiting,'pending validity summary')
    for tid in withdrawn:ck(not any(x.get('task_id')==tid and x['type'] in ('restart_proposed','action_started','action_completed') and x['timestamp_ms']>withdrawn[tid] for x in events),'withdrawn identity revived')
    ck(state['service']['work_completed']==any(tid in done for tid in cs),'work receipt not supported by valid completion')
    return {'episode_id':e['episode_id'],'section':section,'file':file,'run_index':ri,'policy':r['policy'],'errors':errors,'contract_errors':contract_errors,'computed':computed,'peak_units':peak,'events':evidence,'invalid_attempts':sorted(invalid_attempts)}
details=[];packets={}
for section,files in (('main',idx['run_files']),('diagnostic',idx['diagnostic_files'])):
    for file in files:
        packet=read(R/file);packets[file]=packet
        for i,r in enumerate(packet['runs']):details.append(audit(eps[r['evaluation_episode_id']],r,file,i,section))
pairs=[]
for scene in ('CLEAN','RAIN'):
    for i in range(4):
        no=next(p for f,p in packets.items() if f.endswith(f'C4R1-{scene}-NOEVENT.json'))['runs'][i];mid=next(p for f,p in packets.items() if f.endswith(f'C4R1-{scene}-MID.json'))['runs'][i]
        pairs.append({'scene':scene,'run_index':i,'all_actual_requests_equal':no['trace']['agent_requests']==mid['trace']['agent_requests']})
controls=[]
for scene in ('CLEAN','RAIN'):
    original=[d for d in details if d['episode_id']==f'C4R1-{scene}-MID'];local=[d for d in details if d['episode_id']==f'C4R1-{scene}-MID-local_only'];tid=eps[original[0]['episode_id']]['task_stream'][0]['task_id']
    for x,y in zip(original,local):
        equal=all(x['computed']['service_recount'][k][tid]==y['computed']['service_recount'][k][tid] for k in x['computed']['service_recount']) and x['computed']['response_records']==y['computed']['response_records'] and x['computed']['harm_duration_ms']==y['computed']['harm_duration_ms']
        controls.append({'scene':scene,'run_index':x['run_index'],'equal':equal,'main_file':x['file'],'local_file':y['file']})
out={'manifest_sha256':sha(B/'manifest.json'),'hash_errors':hash_errors,'details':details,'noevent_mid_input_pairs':pairs,'local_controls':controls}
(O/'C4_V9_EVENT_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hash_errors':hash_errors,'runs':len(details),'findings':[{'id':d['episode_id'],'run':d['run_index'],'errors':d['errors'],'contract_errors':d['contract_errors']} for d in details if d['errors'] or d['contract_errors']],'input_pairs8':all(x['all_actual_requests_equal'] for x in pairs),'local_pairs8':all(x['equal'] for x in controls)},indent=2))
