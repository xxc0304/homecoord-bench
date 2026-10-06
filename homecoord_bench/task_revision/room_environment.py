"""Uncalibrated synthetic room port. Exact integration between queue events.

Linear CO2 removal and first-order open-window thermal exchange are author
assumptions, not identified physics. Ideal target-clamping thermostat uses
equivalent on-time, not a claim about measured switching or wasted energy.
"""
import math
from copy import deepcopy
from evaluate import get_path, set_path


def validate(e):
    p=e.get('simulation',{}).get('environment')
    if p is None:return None
    if not isinstance(p,dict) or p.get('kind')!='uncalibrated_room_v1' or p.get('calibration_status')!='uncalibrated_synthetic':
        raise ValueError('room port accepts only explicitly uncalibrated synthetic configurations')
    for key in ('source_note','parameter_reference'):
        if not isinstance(p.get(key),str) or not p[key]:raise ValueError('missing parameter provenance')
    for key in ('tick_ms','deadline_ms','horizon_ms','close_delay_ms'):
        if type(p.get(key)) is not int or p[key]<0:raise ValueError('invalid room clock')
    if p['tick_ms']<=0 or not 0<p['deadline_ms']<=p['horizon_ms'] or p['horizon_ms']%p['tick_ms'] or p['deadline_ms']%p['tick_ms']:
        raise ValueError('deadline and horizon must align with a positive sensor tick')
    for key in ('outdoor_temp_c','target_temp_c','target_co2_ppm','co2_floor_ppm','ventilation_rate_ppm_s','exchange_per_s','heat_rate_c_per_s','heater_power_kw'):
        if type(p.get(key)) not in (int,float) or not math.isfinite(p[key]):raise ValueError('invalid room parameter')
    if min(p['ventilation_rate_ppm_s'],p['heat_rate_c_per_s'],p['heater_power_kw'])<=0 or p['exchange_per_s']<0:
        raise ValueError('invalid positive rates or negative exchange')
    state=e['initial_state']['values']
    t=get_path(state,'bedroom.temperature_c');c=get_path(state,'bedroom.co2_ppm')
    if type(t) not in (int,float) or type(c) not in (int,float) or not math.isfinite(t+c):raise ValueError('invalid initial room state')
    if not p['outdoor_temp_c']<t<=p['target_temp_c'] or not p['co2_floor_ppm']<=c or not p['co2_floor_ppm']<p['target_co2_ppm']:
        raise ValueError('room port supports cold-room heating only, with explicit CO2 floor')
    if get_path(state,'devices.window')!='closed' or get_path(state,'devices.heater')!='off':raise ValueError('room starts with idle actuators')
    if p.get('heat_admission') not in ('immediate','after_ventilation'):raise ValueError('invalid heat admission rule')
    if e.get('tool_contract_version')!='strict-v1':raise ValueError('room port needs strict tools')
    if e['conflict_rules'] or e['simulation'].get('lifecycle_contracts') or any(t.get('depends_on') for t in e['task_stream']):
        raise ValueError('environment plus capacity/lifecycle/DAG contracts not yet supported')
    if e['home']['resources']['max_power_kw']<p['heater_power_kw']:raise ValueError('continuous heater exceeds declared nonbinding budget')
    if e.get('constraints'):raise ValueError('room port does not support additional constraints')
    if {t['task_id'] for t in e['task_stream']}!={'bedroom_air','bedroom_heat'} or len(e['task_stream'])!=2:
        raise ValueError('room port currently supports exactly the two room command tasks')
    expected={'bedroom_air':{'devices.window':'open'},'bedroom_heat':{'devices.heater':'enabled'}}
    if len(e['action_grounding'])!=2:raise ValueError('room port requires exactly two grounded commands')
    for g in e['action_grounding']:
        if g['task_id'] not in expected or g.get('start_effects') or g.get('completion_effects')!=expected[g['task_id']]:
            raise ValueError('unsupported room actuator command')
        if g['power_kw']!=0:raise ValueError('command power must not duplicate environment heater energy')
        for effects in (g.get('start_effects',{}),g.get('completion_effects',{}),g.get('effects',{})):
            if any(path.startswith('bedroom.') for path in effects):raise ValueError('agent commands cannot instantly write ambient goals')
    for x in e.get('exogenous_events',[]):
        if any(path.startswith('bedroom.') or path in ('devices.window','devices.heater') for path in x.get('patch',{})):
            raise ValueError('exogenous ambient/actuator forcing not supported by this port')
    return deepcopy(p)


def evolve(t,c,window_open,heater_enabled,dt,p):
    """Closed-form monotone thermal segment with target clamp and ideal duty."""
    k=p['exchange_per_s'] if window_open else 0.0
    g=p['heat_rate_c_per_s'] if heater_enabled else 0.0
    target,out=p['target_temp_c'],p['outdoor_temp_c']
    if k:
        equilibrium=out+g/k
        raw=equilibrium+(t-equilibrium)*math.exp(-k*dt)
        hit=dt
        if g and equilibrium>target and raw>target:
            hit=0 if t>=target else -math.log((target-equilibrium)/(t-equilibrium))/k
        integral=equilibrium*hit+(t-equilibrium)*(-math.expm1(-k*hit))/k
        remainder=dt-hit
        integral+=target*remainder
        end=target if remainder>0 else raw
        on=hit if heater_enabled else 0.0
        if remainder>0:on+=remainder*k*(target-out)/g
    else:
        hit=min(dt,max(0,(target-t)/g)) if g else dt
        end=min(target,t+g*hit)
        integral=t*hit+g*hit*hit/2+end*(dt-hit)
        on=hit if g else 0.0
    co2_end=max(p['co2_floor_ppm'],c-p['ventilation_rate_ppm_s']*dt) if window_open else c
    excess=max(0,c-p['target_co2_ppm'])
    co2_time=min(dt,excess/p['ventilation_rate_ppm_s']) if window_open else dt
    co2_integral=excess*co2_time-(p['ventilation_rate_ppm_s']*co2_time**2/2 if window_open else 0)
    energy=p['heater_power_kw']*on/3.6
    return {'temperature_end_c':end,'co2_end_ppm':co2_end,'heater_on_equivalent_s':on,
            'heater_energy_wh':energy,'open_window_heater_wh':energy if window_open else 0.0,
            'ventilation_temperature_loss_c':max(0,k*(integral-out*dt)),
            'temperature_shortfall_c_s':max(0,target*dt-integral),'co2_excess_ppm_s':max(0,co2_integral)}


class SyntheticRoom:
    def __init__(self,e):
        self.p=validate(e)
        self.clock=e['episode_release_at_ms']
        if self.clock!=0:raise ValueError('room port currently requires epoch zero')
        self.intervals=[]
        self.close_due=None
        self.first_goal=None
        self.deadline=None
        self.totals={k:0.0 for k in ('heater_energy_wh','open_window_heater_wh','ventilation_temperature_loss_c','temperature_shortfall_c_s','co2_excess_ppm_s')}

    def advance(self,state,now):
        now=min(now,self.p['horizon_ms'])
        if now==self.clock:return None
        if now<self.clock:raise ValueError('room time cannot move backwards')
        # Deadline has its own tick, but explicit splitting also protects callers.
        if self.clock<self.p['deadline_ms']<now:
            self.advance(state,self.p['deadline_ms'])
        t,c=get_path(state,'bedroom.temperature_c'),get_path(state,'bedroom.co2_ppm')
        opened=get_path(state,'devices.window')=='open'
        enabled=get_path(state,'devices.heater')=='enabled'
        delta=evolve(t,c,opened,enabled,(now-self.clock)/1000,self.p)
        interval={'start_ms':self.clock,'end_ms':now,'temperature_start_c':t,'co2_start_ppm':c,
                  'window_open':opened,'heater_enabled':enabled,**delta}
        self.intervals.append(interval)
        for key in self.totals:self.totals[key]+=delta[key]
        set_path(state,'bedroom.temperature_c',delta['temperature_end_c'])
        set_path(state,'bedroom.co2_ppm',delta['co2_end_ppm'])
        self.clock=now
        if now==self.p['deadline_ms']:
            self.deadline={'at_ms':now,'temperature_c':delta['temperature_end_c'],'co2_ppm':delta['co2_end_ppm'],
                           'window_closed':not opened,'totals':deepcopy(self.totals)}
        return {'bedroom.temperature_c':delta['temperature_end_c'],'bedroom.co2_ppm':delta['co2_end_ppm']}

    def goal(self,state):
        return (get_path(state,'bedroom.temperature_c')>=self.p['target_temp_c']-1e-8
                and get_path(state,'bedroom.co2_ppm')<=self.p['target_co2_ppm']
                and get_path(state,'devices.window')=='closed')

    def observe(self,state,now):
        if now>self.p['horizon_ms']:return
        if self.first_goal is None and self.goal(state):self.first_goal=now
        if now==self.p['deadline_ms'] and self.deadline is not None:
            self.deadline['window_closed']=get_path(state,'devices.window')=='closed'

    def heating_allowed(self,state):
        return self.p['heat_admission']=='immediate' or (get_path(state,'devices.window')=='closed' and get_path(state,'bedroom.co2_ppm')<=self.p['target_co2_ppm'])

    def result(self):
        return {'source_kind':'synthetic_environment','calibration_status':'uncalibrated_synthetic',
                'common_horizon_ms':self.p['horizon_ms'],'deadline_ms':self.p['deadline_ms'],
                'first_joint_goal_observed_ms':self.first_goal,
                'joint_goal_by_deadline':self.first_goal is not None and self.first_goal<=self.p['deadline_ms'],
                'completion_tardiness_ms':max(0,self.first_goal-self.p['deadline_ms']) if self.first_goal is not None else None,
                'deadline_state_and_integrals':self.deadline,'horizon_integrals':deepcopy(self.totals),
                'maximum_observation_gap_ms':self.p['tick_ms'],
                'command_service_is_not_environment_service':True}
