"""F3 v8 method-independent permissions and public multi-mode requests."""
from copy import deepcopy
import math

POLICIES = ('IndependentMultiAgent', 'ConstraintCoordinator', 'DeadlineAwareCoordinator', 'GateRetryRule')


def validate_f3(e, provider, policy, instructions, shared_gate, synthetic_latency, coordination_delay):
    if e.get('f3_capability_version') != 'fixed-or-selectable-v1':
        raise ValueError('explicit F3 capability contract required')
    if policy not in POLICIES or not shared_gate or synthetic_latency or coordination_delay:
        raise ValueError('four ordinary policies with shared gate and recorded latency only')
    if instructions or getattr(provider, 'prepare_release_batch', None) is not None:
        raise ValueError('request-only providers and empty external instructions required')
    if set(e.get('simulation', {})) != {'command_latency_ms'} or e['exogenous_events'] or e['constraints']:
        raise ValueError('no future events, physical constraints or extra compute/plans in this F3 scope')
    if e['conflict_rules'] != [{'type':'C3','capacity':e['home']['resources']['max_power_kw']}]:
        raise ValueError('only shared public capacity is supported')
    if (e.get('service_delegation',{}).get('principal')!='SyntheticResident'
            or e.get('service_delegation',{}).get('authority')!='explicit_synthetic_service_delegation'):
        raise ValueError('explicit synthetic resident delegation required')
    c=e['mode_capability']
    if set(c) != {'kind','authorized_modes_by_task','selection_boundary','authority'}:
        raise ValueError('exact capability schema required')
    if (c['kind'] not in ('fixed','selectable') or c['selection_boundary'] != 'one_proposal_before_start_no_switch'
            or c['authority'] != 'explicit_synthetic_service_delegation'):
        raise ValueError('invalid authority, capability kind or selection boundary')
    devices={d['agent_id']:d for d in e['public_devices']}
    if len(devices)!=len(e['public_devices']):raise ValueError('duplicate static device')
    for d in devices.values():
        if set(d)!={'agent_id','role','target','service','modes'}:raise ValueError('exact static device schema required')
        if (d['role'] not in {'laundry','drying','dishes','water','meal','cleaning'}
                or d['agent_id']!=d['role'].title()+'Agent' or d['target']!=d['role']+'_device'
                or d['service']!=d['role']+'_completed'):
            raise ValueError('noncanonical static identity')
        ops=[m['operation'] for m in d['modes']]
        if not ops or len(set(ops))!=len(ops) or not set(ops)<={'eco','fast','prepare'}:
            raise ValueError('invalid service modes')
        for m in d['modes']:
            if set(m)!={'operation','duration_ms','resource_units'}:raise ValueError('exact mode schema required')
            for k in ('duration_ms','resource_units'):
                v=m[k]
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
                    raise ValueError('mode costs must be positive finite numbers')
    tasks={t['task_id']:t for t in e['task_stream']}
    if set(tasks)!=set(c['authorized_modes_by_task']):raise ValueError('capability must cover exactly the requests')
    for tid,t in tasks.items():
        if t['release_at_ms']!=0:raise ValueError('F3 v8 all requests are public at zero')
        d=devices[t['agent_id']];physical={m['operation'] for m in d['modes']}
        authorized=c['authorized_modes_by_task'][tid]
        if (not authorized or len(authorized)!=len(set(authorized)) or not set(authorized)<=physical
                or (c['kind']=='fixed' and len(authorized)!=1)
                or (c['kind']=='selectable' and set(authorized)!=physical)):
            raise ValueError('fixed means one mode; selectable means the full same service set')
        if t['requested_service']!=d['service'] or t['acceptable_actions']!=[
                {'target':d['target'],'operation':m['operation']} for m in d['modes']]:
            raise ValueError('physical service equivalence must remain unchanged')
        owner=next(a for a in e['agents'] if a['agent_id']==d['agent_id'])
        expected_tools={d['role']+'_'+op for op in [*authorized,'off']}
        tools=[x for x in e['tool_catalog'] if x['agent_id']==d['agent_id']]
        if set(owner['tools'])!=expected_tools or {x['tool_name'] for x in tools}!=expected_tools:
            raise ValueError('actual tool permissions must match capability contract')
        for m in d['modes']:
            g=next(g for g in e['action_grounding'] if g['task_id']==tid and g['operation']==m['operation'])
            if (g['target']!=d['target'] or g['duration_ms']!=m['duration_ms'] or g['power_kw']!=m['resource_units']
                    or g['completion_effects']!={'devices.'+d['target']:'complete'}):
                raise ValueError('all modes must have declared cost and the same service effect')
            if m['operation'] in authorized:
                tool=next(x for x in tools if x['operation']==m['operation'])
                if (tool['target']!=d['target'] or tool['provides_service']!=d['service']
                        or tool['cost_contract']!={'duration_ms':m['duration_ms'],'resource_units':m['resource_units']}):
                    raise ValueError('public and actual authorized tool cost/service disagree')


def validate_mode_call(e, task_id, action):
    op=action['operation']
    if op=='off':return None
    if op not in e['mode_capability']['authorized_modes_by_task'][task_id]:return 'mode_not_authorized'
    task=next(t for t in e['task_stream'] if t['task_id']==task_id)
    d=next(d for d in e['public_devices'] if d['agent_id']==task['agent_id'])
    m=next(m for m in d['modes'] if m['operation']==op)
    if action['estimated_duration_ms']!=m['duration_ms'] or action['estimated_power_kw']!=m['resource_units']:
        return 'declared_mode_cost_mismatch'
    return None


def public_task(t,d,capability):
    return {'task_id':t['task_id'],'agent_id':t['agent_id'],'release_at_ms':t['release_at_ms'],
            'completion_deadline_ms':t['completion_deadline_ms'],'priority':t['priority'],
            'requested_service':d['service'], 'authorized_modes':deepcopy(capability[t['task_id']]),
            'goal':'Complete the same requested service using one authorized mode; choose once before start, then finish its full nonpreemptive cycle.'}


def build_agent_request(episode,agent,task,*,architecture,current_time_ms,current_state=None,state_version=None,**ignored):
    ds={d['agent_id']:d for d in episode['public_devices']};d=ds[task['agent_id']]
    c=episode['mode_capability'];allowed=c['authorized_modes_by_task'][task['task_id']]
    path='devices.'+d['target'];state=current_state or episode['initial_state']['values']
    modes=[m for m in d['modes'] if m['operation'] in allowed]
    catalog=[]
    for m in [*modes,{'operation':'off','duration_ms':100,'resource_units':0}]:
        op=m['operation']
        catalog.append({'agent_id':d['agent_id'],'tool_name':d['role']+'_'+op,'target':d['target'],
                        'operation':op,'parameters':[],'preconditions':[{'path':path,'op':'eq','value':'idle'}],
                        'provides_service':d['service'] if op!='off' else 'none',
                        'cost_contract':{'duration_ms':m['duration_ms'],'resource_units':m['resource_units']},
                        'description':'Declared synthetic service mode; names do not imply measured energy or quality.'})
    own={'agent_id':d['agent_id'],'role':d['role'],'tools':[x['tool_name'] for x in catalog],
         'observable_state':[path,'coordination_context'],'writable_resources':[path],
         'goal_visibility':'released','constraint_visibility':'public'}
    released=[t for t in episode['task_stream'] if t['release_at_ms']<=current_time_ms]
    return {'request_id':f"F3-public-home:{architecture}:{task['task_id']}",'episode_id':'F3-public-home',
            'base_episode_id':'F3-public-home','architecture':architecture,'current_time_ms':current_time_ms,
            'state_version':state_version if state_version is not None else episode['initial_state']['version'],
            'agent':own,'task':public_task(task,d,c['authorized_modes_by_task']),
            'mode_capability':deepcopy(c),
            'state':{'devices':{d['target']:state['devices'][d['target']]},'coordination_context':{
                'resource_capacity_units':episode['home']['resources']['max_power_kw'],
                'requests':[public_task(t,ds[t['agent_id']],c['authorized_modes_by_task']) for t in released],
                'static_devices':deepcopy(episode['public_devices'])}},
            'goals':[{'path':'devices.'+ds[t['agent_id']]['target'],'op':'eq','value':'complete'} for t in released],
            'constraints':[],'allowed_tools':own['tools'],'available_actions':catalog,'pending_proposals':[]}
