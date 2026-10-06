"""Independent actuator/thermal endpoint, dimensional balance and integral audit."""
import math
from copy import deepcopy
from evaluate import get_path,set_path


def close(a,b):
    assert math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-7),(a,b)


def audit(e,trace,reported):
    p=e['simulation']['environment']
    totals={k:0.0 for k in reported['horizon_integrals']}
    clock=0;temp=e['initial_state']['values']['bedroom']['temperature_c'];co2=e['initial_state']['values']['bedroom']['co2_ppm']
    state=deepcopy(e['initial_state']['values']);by_end={x['end_ms']:x for x in trace['environment_intervals']}
    deadline_totals=None;deadline_interval=None
    for x in trace['environment_intervals']:
        assert x['start_ms']==clock and x['end_ms']>clock
        close(x['temperature_start_c'],temp);close(x['co2_start_ppm'],co2)
        dt=(x['end_ms']-clock)/1000
        k=p['exchange_per_s'] if x['window_open'] else 0
        g=p['heat_rate_c_per_s'] if x['heater_enabled'] else 0
        if k:
            eq=p['outdoor_temp_c']+g/k
            predicted=eq+(temp-eq)*math.exp(-k*dt)
        else:predicted=temp+g*dt
        close(x['temperature_end_c'],min(p['target_temp_c'],predicted))
        close(x['temperature_end_c'],temp+p['heat_rate_c_per_s']*x['heater_on_equivalent_s']-x['ventilation_temperature_loss_c'])
        expected_co2=max(p['co2_floor_ppm'],co2-p['ventilation_rate_ppm_s']*dt) if x['window_open'] else co2
        close(x['co2_end_ppm'],expected_co2)
        close(x['heater_energy_wh'],p['heater_power_kw']*x['heater_on_equivalent_s']/3.6)
        close(x['open_window_heater_wh'],x['heater_energy_wh'] if x['window_open'] else 0)
        assert 0<=x['heater_on_equivalent_s']<=dt+1e-8
        if not x['heater_enabled']:close(x['heater_on_equivalent_s'],0)
        assert all(x[key]>=-1e-8 for key in totals)
        # Temperature integral is independently recoverable from loss, or linear gain when closed.
        if k:
            integral=x['ventilation_temperature_loss_c']/k+p['outdoor_temp_c']*dt
        elif g:
            on=x['heater_on_equivalent_s']
            integral=temp*on+g*on*on/2+p['target_temp_c']*(dt-on)
        else:integral=temp*dt
        close(x['temperature_shortfall_c_s'],max(0,p['target_temp_c']*dt-integral))
        excess=max(0,co2-p['target_co2_ppm'])
        time=min(dt,excess/p['ventilation_rate_ppm_s']) if x['window_open'] else dt
        close(x['co2_excess_ppm_s'],excess*time-(p['ventilation_rate_ppm_s']*time*time/2 if x['window_open'] else 0))
        for key in totals:totals[key]+=x[key]
        clock=x['end_ms'];temp=x['temperature_end_c'];co2=x['co2_end_ppm']
        if clock==p['deadline_ms']:
            deadline_totals=deepcopy(totals);deadline_interval=x
    assert clock==p['horizon_ms'] and deadline_totals is not None
    for key in totals:
        close(totals[key],reported['horizon_integrals'][key])
        close(deadline_totals[key],reported['deadline_state_and_integrals']['totals'][key])
    first_goal=None;deadline_closed=None;pending_close=None
    def goal():
        return (get_path(state,'bedroom.temperature_c')>=p['target_temp_c']-1e-8
                and get_path(state,'bedroom.co2_ppm')<=p['target_co2_ppm']
                and get_path(state,'devices.window')=='closed')
    if goal():first_goal=0
    for event in trace['events']:
        if event['type']=='state_update' and event.get('source')=='synthetic_environment':
            x=by_end[event['timestamp_ms']]
            assert x['window_open']==(get_path(state,'devices.window')=='open')
            assert x['heater_enabled']==(get_path(state,'devices.heater')=='enabled')
            close(event['patch']['bedroom.temperature_c'],x['temperature_end_c'])
            close(event['patch']['bedroom.co2_ppm'],x['co2_end_ppm'])
        if event['type']=='action_completed':
            g=next(g for g in e['action_grounding'] if g['task_id']==event['task_id'])
            assert event['effects']==g['completion_effects']
        if event['type']=='automatic_window_close_requested':
            assert get_path(state,'bedroom.co2_ppm')<=p['target_co2_ppm']
            assert event['confirm_at_ms']==event['timestamp_ms']+p['close_delay_ms']
            assert get_path(state,'devices.window')=='open' and pending_close is None
            pending_close=event['confirm_at_ms']
        if event['type']=='state_update' and event.get('source')=='automatic_window_close':
            assert event['timestamp_ms']==pending_close
            assert event['patch']=={'devices.window':'closed'}
            pending_close=None
        patch=event.get('patch',{}) if event['type']=='state_update' else event.get('effects',{}) if event['type']=='action_completed' else {}
        for path,value in patch.items():set_path(state,path,value)
        if event['timestamp_ms']<=p['horizon_ms'] and first_goal is None and goal():first_goal=event['timestamp_ms']
        if event['timestamp_ms']==p['deadline_ms']:deadline_closed=get_path(state,'devices.window')=='closed'
    assert state==trace['final_state']
    close(temp,get_path(state,'bedroom.temperature_c'));close(co2,get_path(state,'bedroom.co2_ppm'))
    assert reported['calibration_status']=='uncalibrated_synthetic'
    assert reported['first_joint_goal_observed_ms']==first_goal
    assert reported['joint_goal_by_deadline']==(first_goal is not None and first_goal<=p['deadline_ms'])
    assert reported['completion_tardiness_ms']==(max(0,first_goal-p['deadline_ms']) if first_goal is not None else None)
    close(reported['deadline_state_and_integrals']['temperature_c'],deadline_interval['temperature_end_c'])
    close(reported['deadline_state_and_integrals']['co2_ppm'],deadline_interval['co2_end_ppm'])
    assert reported['deadline_state_and_integrals']['window_closed']==deadline_closed
    return {'actuator_replay':'passed','thermal_and_CO2_endpoints':'passed','unit_and_heat_balance':'passed',
            'deadline_and_horizon_integrals':'passed','interval_count':len(trace['environment_intervals'])}
