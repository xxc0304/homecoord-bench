import json,hashlib,copy
from pathlib import Path
ROOT=Path(r'.');OUT=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
inputs=read(ROOT/'homecoord_bench/task_revision/fixtures/protection_v5_inputs.json')
episodes={e['episode_id']:e for e in inputs['episodes']}
manifest=read(ROOT/'homecoord_bench/task_revision/fixtures/protection_v5_manifest.json')
hash_errors=[]
for n,h in manifest['source_sha256'].items():
    if sha(ROOT/'homecoord_bench/task_revision'/n)!=h:hash_errors.append(n)
for p,h in manifest['artifact_sha256'].items():
    if sha(ROOT/p)!=h:hash_errors.append(p)
packet=read(ROOT/'homecoord_bench/results/protection_v5_offline_20261002.json')
def get(s,path):
    for k in path.split('.'):s=s[k]
    return s
def put(s,path,val):
    ks=path.split('.')
    for k in ks[:-1]:s=s.setdefault(k,{})
    s[ks[-1]]=copy.deepcopy(val)
def holds(s,c):
    a,b=get(s,c['path']),c['value']
    return a==b if c['op']=='eq' else a!=b if c['op']=='neq' else a<=b if c['op']=='lte' else a>=b
def leaves(s,path=''):
    for k,v in s.items():
        p=f'{path}.{k}' if path else k
        if isinstance(v,dict):yield from leaves(v,p)
        else:yield p,v
details=[]
for ri,run in enumerate(packet['runs']):
    e=episodes[run['episode_id']];tr=run['trace'];result=run['result'];tasks={t['task_id']:t for t in e['task_stream']}
    state=copy.deepcopy(e['initial_state']['values']);version=e['initial_state']['version'];clock=0;harm=0;active={};starts={};done={};closed=set();expected_status={};admitted=set();snapshots={};errors=[];leaks=[];evidence=[];reserved={}
    p=e['user_delegations'][0];low=e['task_stream'][1]['task_id'];protect=p['protected_path'];safe='reading' if p['target']=='study_light' else 'closed'
    def check(ok,why):
        if not ok:errors.append(why)
    for ei,x in enumerate(tr['events']):
        at=x['timestamp_ms'];kind=x['type'];tid=x.get('task_id');pid=x.get('proposal_id')
        check(at>=clock,f'events[{ei}]: clock reversed')
        if get(state,protect) is True and get(state,'devices.'+p['target'])!=safe:harm+=at-clock
        clock=at
        if kind=='task_released':
            check(at==tasks[tid]['release_at_ms'],f'events[{ei}]: wrong publication')
            snapshots[tid]=(copy.deepcopy(state),version,ei)
            if tid==low:expected_status[tid]='rejected_terminal' if get(state,protect) else 'completed'
        if kind=='request_admitted':
            check(tid==low and get(state,protect) is False and at==tasks[tid]['release_at_ms'],f'events[{ei}]: invalid admission');admitted.add(tid)
        if kind=='request_terminal_rejected':
            check(expected_status[tid]=='rejected_terminal' and tid not in closed and x['terminal'] is True and at==tasks[tid]['release_at_ms'],f'events[{ei}]: invalid terminal reject');closed.add(tid)
        if tid in closed:check(kind in ['task_released','request_terminal_rejected'],f'events[{ei}]: closed request revived')
        if kind=='action_reserved':reserved[pid]=x
        if kind=='action_started':
            task=tasks[tid];g=next(g for g in e['action_grounding'] if (g['task_id'],g['target'],g['operation'])==(tid,x['target'],x['operation']))
            check(at>=task['release_at_ms'] and x['agent_id']==task['agent_id'],f'events[{ei}]: publication/identity')
            check(all(holds(state,r) for r in x['requires']),f'events[{ei}]: failed precondition')
            check(x['duration_ms']==g['duration_ms'] and x['power_kw']==g['power_kw'],f'events[{ei}]: grounding cost')
            check(x['start_effects']==g['start_effects']=={} and x['completion_effects']==g['completion_effects'],f'events[{ei}]: wrong declared effects')
            check(at==reserved[pid]['scheduled_start_ms'] and at>=reserved[pid]['timestamp_ms']+100,f'events[{ei}]: reservation/command clock')
            check(x['state_version_at_start']==version,f'events[{ei}]: start version')
            active[pid]=(ei,x,g);starts[tid]=(ei,at)
        if kind=='action_completed':
            si,s,g=active.pop(pid)
            check(all(x[k]==s[k] for k in ['task_id','agent_id','target','operation']) and at==s['timestamp_ms']+g['duration_ms'],f'events[{ei}]: false completion')
            check(x['effects']==g['completion_effects'],f'events[{ei}]: wrong completion effects')
            done[tid]=(ei,at)
        if kind in ['state_update','action_completed']:
            patch=x['patch'] if kind=='state_update' else x['effects']
            if kind=='state_update':check(any(v['at_ms']==at and v['patch']==patch for v in e['exogenous_events']),f'events[{ei}]: unexpected external patch')
            for path,val in patch.items():put(state,path,val)
            version+=1;check(version==x['new_state_version'],f'events[{ei}]: update version')
        evidence.append({'event_index':ei,'type':kind,'timestamp_ms':at,'task_id':tid})
    check(not active and state==tr['final_state'] and version==tr['final_state_version'],'final replay mismatch')
    for qi,req in enumerate(tr['agent_requests']):
        tid=req['task']['task_id'];task=tasks[tid];agent=next(a for a in e['agents'] if a['agent_id']==task['agent_id']);ss,sv,se=snapshots[tid]
        check(tid not in closed and req['current_time_ms']==task['release_at_ms'] and req['state_version']==sv,f'agent_requests[{qi}]: closed/wrong publication snapshot')
        check(req['task']==task and req['agent']==agent and req['allowed_tools']==agent['tools'],f'agent_requests[{qi}]: task or permission mismatch')
        check(req['available_actions']==[z for z in e['tool_catalog'] if z['agent_id']==agent['agent_id']],f'agent_requests[{qi}]: available tool mismatch')
        check(req['goals']==[] and req['constraints']==agent['policy_constraints'],f'agent_requests[{qi}]: incorrect local goals/constraints')
        for path,val in leaves(req['state']):
            check(get(ss,path)==val and any(path==q or path.startswith(q+'.') for q in agent['observable_state']+agent['writable_resources']),f'agent_requests[{qi}]: hidden or incorrect state')
        check('exogenous_events' not in req and 'task_stream' not in req,'future payload explicitly included')
        for field in ['episode_id','request_id']:
            if any(tag in req[field] for tag in ['CONFLICT','SAFE','legality','equal_response']):leaks.append({'request_index':qi,'field':field,'value':req[field],'time_ms':req['current_time_ms']})
    completed={tid:tid in done for tid in tasks}
    metrics={'task_correct_action_started':{tid:tid in starts for tid in tasks},'task_correct_action_completed':completed,'task_service':completed,'task_start_wait_ms':{tid:starts[tid][1]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()},'task_completion_latency_ms':{tid:done[tid][1]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()},'task_completion_tardiness_ms':{tid:max(0,done[tid][1]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()},'task_deadline_met':{tid:tid in done and done[tid][1]<=t['completion_deadline_ms'] for tid,t in tasks.items()},'task_action_finish_time_ms':{tid:done[tid][1]-e['episode_release_at_ms'] if tid in done else None for tid in tasks},'task_unstarted_count':sum(tid not in starts for tid in tasks),'task_incomplete_count':sum(tid not in done for tid in tasks),'served_task_count':len(done),'serviceable_task_count':len(tasks),'task_service_rate':len(done)/len(tasks),'state_constraint_violation_duration_ms':harm,'request_status':{low:'rejected_terminal' if low in closed else 'completed' if low in done else 'unresolved'},'terminal_rejected_task_ids':sorted(closed)}
    metrics['all_deadlines_met']=all(metrics['task_deadline_met'].values())
    for key,val in metrics.items():check(result[key]==val,f'result.{key} mismatch: {result[key]} != {val}')
    for tid in closed:
        check(tid not in result['model_latency_by_task_ms'],'terminal request has model latency')
        check(all(x.get('task_id')!=tid or x['type'] in ['task_released','request_terminal_rejected'] for x in tr['events']),'terminal request performed activity')
    check(set(result['model_latency_by_task_ms'])=={r['task']['task_id'] for r in tr['agent_requests']},'calls and latency keys disagree')
    check(run['audit']['request_status']==metrics['request_status'] and run['audit']['protection_loss_ms']==harm,'author recount status/loss mismatch')
    details.append({'run_index':ri,'episode_id':e['episode_id'],'policy':run['policy'],'execution_scoring_errors':errors,'input_channel_findings':leaks,'computed':metrics,'evidence':evidence})
out={'manifest_sha256':sha(ROOT/'homecoord_bench/task_revision/fixtures/protection_v5_manifest.json'),'hash_errors':hash_errors,'configurations':len(episodes),'runs':details}
(OUT/'C1_V5_EVENT_AUDIT_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hash_errors':hash_errors,'runs':len(details),'execution_scoring_errors':[{ 'run':r['run_index'],'errors':r['execution_scoring_errors']} for r in details if r['execution_scoring_errors']],'requests_with_labeled_ids':sum(len(r['input_channel_findings'])//2 for r in details),'all_runs_have_labeled_ids':all(r['input_channel_findings'] for r in details),'representatives':[r for r in details if r['run_index']%4==0]},ensure_ascii=False,indent=2))
