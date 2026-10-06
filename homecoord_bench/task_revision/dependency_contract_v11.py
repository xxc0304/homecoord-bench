"""Explicit single-batch dependency contract, request-only public tools."""
from copy import deepcopy
from runtime.protocol import build_agent_request as base_request
POLICIES=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')
def validate_v11(e,provider,policy,instructions,gate):
    if e.get('dependency_revision')!='v11-single-batch':raise ValueError('explicit dependency v11 required')
    if policy not in POLICIES or instructions or not gate or getattr(provider,'prepare_release_batch',None):raise ValueError('ordinary shared-gate request-only policies required')
    if set(e['simulation'])-{'command_latency_ms','lifecycle_contracts'}:raise ValueError('mixed execution contract')
    if e['batch_binding']!={'wash':'batch_1','dry':'batch_1'}:raise ValueError('single explicit shared batch only')
    if next(t for t in e['task_stream'] if t['task_id']=='dry').get('depends_on')!=['wash']:raise ValueError('trusted wash prerequisite required')
    for x in e['exogenous_events']:
        if any(p.startswith('service.') for p in x['patch']):raise ValueError('world cannot provide trusted service receipts')
def build_agent_request(e,agent,task,**kwargs):
    public=deepcopy(e);public['episode_id']=public['base_episode_id']='HC-M12'
    local=deepcopy(agent);local['goal_visibility']='local';local['constraint_visibility']='local';local['policy_constraints']=[]
    t={k:deepcopy(task[k]) for k in ('task_id','agent_id','release_at_ms','completion_deadline_ms','priority')}
    t['goal']='Execute authorized service for the declared batch; trusted completion gates prerequisites.'
    t['batch_id']=e['batch_binding'].get(task['task_id'])
    public['tool_catalog']=[{k:deepcopy(x[k]) for k in ('agent_id','tool_name','target','operation','parameters','preconditions','cost_contract')} for x in e['tool_catalog']]
    kwargs['include_evaluation_hints']=False;kwargs['request_id']=f"HC-M12:{kwargs['architecture']}:{task['task_id']}"
    return base_request(public,local,t,**kwargs)
