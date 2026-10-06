import json,copy,hashlib
from pathlib import Path
R=Path(r'.');B=R/'homecoord_bench/task_revision/fixtures/f3_v8';O=Path('outputs')
# Shared independent state/resource replay from the previous F2 review, with service modes separated from off.
src=Path('work/audit_f2_v7.py').read_text(encoding='utf-8');exec(src[src.index('def get('):src.index('eps=')])
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
eps={e['episode_id']:e for e in read(B/'inputs.json')['episodes']};idx=read(B/'index.json');manifest=read(B/'manifest.json');hash_errors=[]
for section in ('source_sha256','artifact_sha256'):
    for p,h in manifest[section].items():
        if sha(R/p)!=h:hash_errors.append(p)
def pt(t,d,c):return {'task_id':t['task_id'],'agent_id':t['agent_id'],'release_at_ms':t['release_at_ms'],'completion_deadline_ms':t['completion_deadline_ms'],'priority':t['priority'],'requested_service':d['service'],'authorized_modes':c[t['task_id']],'goal':'Complete the same requested service using one authorized mode; choose once before start, then finish its full nonpreemptive cycle.'}
def expected_input(e,task,policy,state,version):
    ds={d['agent_id']:d for d in e['public_devices']};d=ds[task['agent_id']];c=e['mode_capability'];path='devices.'+d['target'];allowed=c['authorized_modes_by_task'][task['task_id']];modes=[m for m in d['modes'] if m['operation'] in allowed]+[{'operation':'off','duration_ms':100,'resource_units':0}]
    tools=[{'agent_id':d['agent_id'],'tool_name':d['role']+'_'+m['operation'],'target':d['target'],'operation':m['operation'],'parameters':[],'preconditions':[{'path':path,'op':'eq','value':'idle'}],'provides_service':d['service'] if m['operation']!='off' else 'none','cost_contract':{'duration_ms':m['duration_ms'],'resource_units':m['resource_units']},'description':'Declared synthetic service mode; names do not imply measured energy or quality.'} for m in modes]
    agent={'agent_id':d['agent_id'],'role':d['role'],'tools':[x['tool_name'] for x in tools],'observable_state':[path,'coordination_context'],'writable_resources':[path],'goal_visibility':'released','constraint_visibility':'public'}
    tasks=e['task_stream'];return {'request_id':'F3-public-home:'+policy+':'+task['task_id'],'episode_id':'F3-public-home','base_episode_id':'F3-public-home','architecture':policy,'current_time_ms':0,'state_version':version,'agent':agent,'task':pt(task,d,c['authorized_modes_by_task']),'mode_capability':c,'state':{'devices':{d['target']:get(state,path)},'coordination_context':{'resource_capacity_units':e['home']['resources']['max_power_kw'],'requests':[pt(t,ds[t['agent_id']],c['authorized_modes_by_task']) for t in tasks],'static_devices':e['public_devices']}},'goals':[{'path':'devices.'+ds[t['agent_id']]['target'],'op':'eq','value':'complete'} for t in tasks],'constraints':[],'allowed_tools':agent['tools'],'available_actions':tools,'pending_proposals':[]}
audit_src=src[src.index('def audit('):src.index('details=[]')]
audit_src=audit_src.replace("x['operation']=='prepare'","(x['operation'] in e['mode_capability']['authorized_modes_by_task'][tid] or x['operation']=='off')")
audit_src=audit_src.replace("starts.setdefault(tid,(j,at));load=","starts.setdefault(tid,(j,at)) if x['operation']!='off' else None;load=")
audit_src=audit_src.replace("done.setdefault(tid,(j,at));intervals.append(","done.setdefault(tid,(j,at)) if x['operation']!='off' else None;intervals.append(")
audit_src=audit_src.replace("'units':s['power_kw']}","'units':s['power_kw'],'operation':s['operation']}")
audit_src=audit_src.replace("for k,v in m.items():check(res[k]==v,'result.'+k)","for k,v in m.items():\n        if k not in ('task_service','served_task_count','serviceable_task_count','task_service_rate'):check(res[k]==v,'result.'+k)")
exec(audit_src)
details=[];lookup={};packets={}
def extended(e,r,file,ri,section):
    d=audit(e,r,file,ri,section);events=r['trace']['events'];errors=d['errors'];allowed=e['mode_capability']['authorized_modes_by_task'];commits={};starts={};finishes={}
    def check(ok,s):
        if not ok:errors.append(s)
    for j,x in enumerate(events):
        tid=x.get('task_id');pid=x.get('proposal_id')
        if x['type']=='mode_selection_committed':
            check(tid not in commits and x['operation'] in allowed[tid] and x['capability_kind']==e['mode_capability']['kind'] and x['selection_boundary']=='before_start_no_switch',f'e{j} commit permission/uniqueness');commits[tid]=(j,x)
        if x['type']=='action_reserved':
            action=next(p for c in r['calls'] for p in c['decision']['actions'] if p['proposal_id']==pid)
            if action['operation']!='off':check(tid in commits and commits[tid][0]<j and commits[tid][1]['proposal_id']==pid,f'e{j} reservation before commit')
        if x['type']=='action_started' and x['operation']!='off':
            cj,c=commits[tid];check(cj<j and c['timestamp_ms']<x['timestamp_ms'] and (c['proposal_id'],c['operation'])==(pid,x['operation']),f'e{j} mode changed');starts[tid]=x
        if x['type']=='action_completed' and x['operation']!='off':finishes[tid]=x['timestamp_ms']
    actual_cost={tid:None for tid in allowed}
    for x in d['intervals']:
        if x['operation']!='off':actual_cost[x['task_id']]=x['units']*(x['end_ms']-x['start_ms'])
    ext={'selected_mode_by_task':{tid:commits[tid][1]['operation'] if tid in commits else None for tid in allowed},'realized_mode_by_task':{tid:starts[tid]['operation'] if tid in starts else None for tid in allowed},'task_executed_resource_time_units_ms':actual_cost,'total_executed_resource_time_units_ms':sum(x['units']*(x['end_ms']-x['start_ms']) for x in d['intervals']),'all_services_completed':len(finishes)==len(allowed),'all_service_completion_ms':max(finishes.values()) if len(finishes)==len(allowed) else None,'latest_observed_service_completion_ms':max(finishes.values(),default=None)}
    boundaries=sorted({t for x in d['intervals'] for t in (x['start_ms'],x['end_ms'])})
    integral=sum((right-left)*sum(x['units'] for x in d['intervals'] if x['start_ms']<=left<x['end_ms']) for left,right in zip(boundaries,boundaries[1:]))
    check(integral==ext['total_executed_resource_time_units_ms'],'piecewise load integral')
    for call in r['calls']:
        actions=call['decision']['actions'];check(len(actions)<=1,'more than one action per request')
        if section=='main':
            action=actions[0];tid=call['request']['task']['task_id'];tool=next(t for t in call['request']['available_actions'] if t['operation']==action['operation'])
            check(action['estimated_duration_ms']==tool['cost_contract']['duration_ms'] and action['estimated_power_kw']==tool['cost_contract']['resource_units'],'proposal cost mismatch')
    for k,v in ext.items():check(r['audit'][k]==v,'audit.'+k)
    d.update({'selector':r['selector'],'case':r.get('case'),'world':e['evaluation_world_id'],'kind':e['mode_capability']['kind'],'commits':{tid:{'event_index':j,**x} for tid,(j,x) in commits.items()},'extended_metrics':ext})
    if section=='main':
        ds={z['agent_id']:z for z in e['public_devices']}
        short=lambda ms:min(ms,key=lambda m:(m['duration_ms'],m['resource_units'],m['operation']))
        authorized={t['task_id']:[m for m in ds[t['agent_id']]['modes'] if m['operation'] in allowed[t['task_id']]] for t in e['task_stream']}
        pressure=sum(short(ms)['resource_units'] for ms in authorized.values())
        prefer_short=r['selector']=='short_duration' or (r['selector']=='capacity_pressure' and pressure<=d['capacity'])
        expected_modes={tid:(short(ms) if prefer_short else min(ms,key=lambda m:(m['resource_units'],m['duration_ms'],m['operation'])))['operation'] for tid,ms in authorized.items()}
        check(ext['selected_mode_by_task']==expected_modes,'public selection rule mismatch')
    if section=='diagnostic':
        case=r['case'];target=[t['task_id'] for t in e['task_stream'] if len(t['acceptable_actions'])>1]
        if case=='forbidden_fast':
            for tid in target:check(any(x['type']=='action_rejected' and x.get('task_id')==tid and x['reason']=='mode_not_authorized' for x in events) and tid not in commits and tid not in starts and not any(x['type']=='action_reserved' and x.get('task_id')==tid for x in events),f'{case} bypass '+tid)
        elif case=='cost_lie':check(not d['intervals'] and not commits and all(any(x['type']=='action_rejected' and x.get('task_id')==tid and x['reason']=='declared_mode_cost_mismatch' for x in events) for tid in allowed),'cost lie bypass')
        else:check(not any(d['computed']['task_correct_action_completed'].values()) and ext['all_service_completion_ms'] is None and ext['total_executed_resource_time_units_ms']==0,'off/noop counted service')
    return d
for file in idx['run_files']:
    packet=read(R/file);packets[file]=packet;e=eps[packet['episode_id']]
    for i,r in enumerate(packet['runs']):
        d=extended(e,r,file,i,'main');details.append(d);lookup[(e['episode_id'],r['policy'],r['selector'])]=d
for file in idx['diagnostic_files']:
    packet=read(R/file)
    for i,r in enumerate(packet['runs']):details.append(extended(eps[r['evaluation_episode_id']],r,file,i,'diagnostic'))
def diff(a,b):
    x,y=a['extended_metrics'],b['extended_metrics'];delta=lambda v,w:v-w if v is not None and w is not None else None
    return {'all_service_completion_ms_delta':delta(x['all_service_completion_ms'],y['all_service_completion_ms']),'resource_time_units_ms_delta':x['total_executed_resource_time_units_ms']-y['total_executed_resource_time_units_ms'],'both_all_services_completed':x['all_services_completed'] and y['all_services_completed'],'task_start_wait_ms_delta':{tid:delta(v,b['computed']['task_start_wait_ms'][tid]) for tid,v in a['computed']['task_start_wait_ms'].items()},'task_completion_tardiness_ms_delta':{tid:delta(v,b['computed']['task_completion_tardiness_ms'][tid]) for tid,v in a['computed']['task_completion_tardiness_ms'].items()}}
contrasts=read(B/'contrasts.json');contrast_checks=[]
for kind,rows in contrasts.items():
    if not isinstance(rows,list):continue
    for i,row in enumerate(rows):
        world=row['world'];selector=row.get('selector','low_resource');pol=row['policy'];select=next(e for e in eps.values() if e['evaluation_world_id']==world and e['mode_capability']['kind']=='selectable')
        if kind=='fixed_mode_scheduling':
            fixed=next(e for e in eps.values() if e['evaluation_world_id']==world and e['mode_capability']['kind']=='fixed' and {tid:ops[0] for tid,ops in e['mode_capability']['authorized_modes_by_task'].items()}==row['fixed_vector']);ar=lookup[(fixed['episode_id'],pol,'low_resource')];br=lookup[(fixed['episode_id'],row['control_policy'],'low_resource')]
        else:
            ar=lookup[(select['episode_id'],pol,selector)];br=lookup[(row.get('fixed_control',row.get('matched_fixed_episode')),pol,'low_resource')]
        if kind=='mode_matched_controls':
            ok=ar['computed']==br['computed'] and ar['extended_metrics']==br['extended_metrics'] and row['selected_vector']==ar['extended_metrics']['selected_mode_by_task'];computed={'all_core_metrics_and_mode_cost_equal':ok}
        else:computed=diff(ar,br);ok=all(row[k]==v for k,v in computed.items())
        ok=ok and ar['world']==br['world'] and (kind=='fixed_mode_scheduling' or ar['policy']==br['policy'])
        contrast_checks.append({'section':kind,'index':i,'equal':ok,'left':{'file':ar['file'],'run_index':ar['run_index']},'right':{'file':br['file'],'run_index':br['run_index']},'computed':computed})
information_checks=[]
for file,packet in packets.items():
    clean=[]
    for r in packet['runs']:
        qs=copy.deepcopy(r['trace']['agent_requests'])
        for q in qs:q.pop('architecture');q.pop('request_id')
        clean.append(qs)
    information_checks.append({'file':file,'full_inputs_equal_except_policy_identity':all(q==clean[0] for q in clean)})
out={'manifest_sha256':sha(B/'manifest.json'),'hash_errors':hash_errors,'details':details,'contrast_checks':contrast_checks,'information_checks':information_checks}
(O/'F3_V8_EVENT_AUDIT_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hash_errors':hash_errors,'rows':len(details),'errors':[{'file':d['file'],'run':d['run_index'],'errors':d['errors']} for d in details if d['errors']],'contrasts':len(contrast_checks),'contrast_errors':[c for c in contrast_checks if not c['equal']]},indent=2))
