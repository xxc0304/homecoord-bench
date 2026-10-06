"""C2 demand disposition and common trusted-controller permissions."""
from copy import deepcopy
from runtime.protocol import build_agent_request as base_request
AUTHORITY={'principal':'SyntheticResident','basis':'explicit_uncalibrated_synthetic_delegation',
    'automatic_window_close':{'sensor_tick_ms':1000,'co2_threshold_ppm':900,'confirmation_delay_ms':3000,'command_energy_wh':0},
    'thermostat':{'kind':'ideal_target_clamp','heater_power_kw':2,'target_temp_c':21,'switching_cost_wh':0},
    'heating_admission':{'owner':'shared_trusted_controller','rules':['immediate','after_ventilation'],'extra_compute_ms':0}}
def validate_v12(e,provider,policy,instructions,gate):
    if e.get('c2_revision')!='v12-demand-disposition':raise ValueError('explicit C2 v12 required')
    if e.get('controller_authority')!=AUTHORITY:raise ValueError('common synthetic controller permissions and costs required')
    if set(e['simulation'])!={'command_latency_ms','environment'}:raise ValueError('no mixed runtime features')
    if policy!='ConstraintCoordinator' or instructions or not gate or getattr(provider,'prepare_release_batch',None):raise ValueError('scoped request-only rule comparison required')
    p=e['simulation']['environment']
    if any(p[k]!=v for k,v in {'tick_ms':1000,'close_delay_ms':3000,'target_co2_ppm':900,'target_temp_c':21,'heater_power_kw':2}.items()):raise ValueError('controller authority and environment disagree')
    air=next(t for t in e['task_stream'] if t['task_id']=='bedroom_air')
    if air.get('demand_rule')!={'path':'bedroom.co2_ppm','threshold_ppm':900,'satisfied_action':'keep_window_closed','unsatisfied_action':'ventilate_then_trusted_close'}:raise ValueError('explicit demand-aware air request required')
def build_agent_request(e,agent,task,**kwargs):
    public=deepcopy(e);public['episode_id']=public['base_episode_id']='HC-M06'
    local=deepcopy(agent);local['goal_visibility']='local';local['constraint_visibility']='local';local['policy_constraints']=[]
    t={k:deepcopy(task[k]) for k in ('task_id','agent_id','release_at_ms','completion_deadline_ms','priority','goal','demand_rule') if k in task}
    public['tool_catalog']=[{k:deepcopy(x[k]) for k in ('agent_id','tool_name','target','operation','parameters','preconditions','cost_contract')} for x in e['tool_catalog']]
    kwargs['include_evaluation_hints']=False;kwargs['request_id']=f"HC-M06:{kwargs['architecture']}:{task['task_id']}"
    return base_request(public,local,t,**kwargs)

def disposition_metrics(e,events):
    tasks={t['task_id']:t for t in e['task_stream']}
    handled={};kinds={};admitted=set()
    for x in events:
        if x['type'] in ('action_reserved','environment_admission_waiting','request_satisfied_without_actuation'):admitted.add(x['task_id'])
        if x['type']=='request_satisfied_without_actuation':handled[x['task_id']]=x['timestamp_ms'];kinds[x['task_id']]='satisfied_without_actuation'
        if x['type']=='action_completed':handled[x['task_id']]=x['timestamp_ms'];kinds[x['task_id']]='command_completed'
    return {'task_admission_legal':{tid:tid in admitted for tid in tasks},
            'task_correct_disposition':{tid:tid in handled for tid in tasks},
            'task_disposition':{tid:kinds.get(tid,'unresolved') for tid in tasks},
            'task_disposition_latency_ms':{tid:handled[tid]-t['release_at_ms'] if tid in handled else None for tid,t in tasks.items()},
            'task_disposition_deadline_met':{tid:tid in handled and handled[tid]<=t['completion_deadline_ms'] for tid,t in tasks.items()}}
