"""Shared-clock C2 synthetic integration and parameter sensitivity; no API."""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.append(str(ROOT.parent))
from make_representative_revision_drafts import load_candidate,_tool
from homecoord_bench.task_revision.milestone import FixedProposals
from homecoord_bench.task_revision.event_simulator_v4 import run_event_simulation
from homecoord_bench.task_revision.room_audit import audit


class ConditionalProposals(FixedProposals):
    def decide(self,request,instructions=''):
        if request['task']['task_id']=='bedroom_air' and request['state']['bedroom']['co2_ppm']<=900:
            return {'response_type':'defer','actions':[],'accepted_proposal_ids':[],'rejected_proposal_ids':[],
                    'defer_until_ms':None,'reason_code':'no_applicable_action'}
        return super().decide(request,instructions)


def episode(co2=1600,vent=2.5,heat=.025,admission='immediate'):
    e=load_candidate('HC-M06')
    e['episode_id']=f'ROOM-{co2}-V{vent}-H{heat}-{admission}'
    e['base_episode_id']='HC-M06'
    e['review_status']='author_defined_uncalibrated_development_only'
    e['tool_contract_version']='strict-v1'
    e['conflict_rules']=[];e['constraints']=[]
    e['initial_state']['values']['bedroom']['co2_ppm']=co2
    e['simulation']={'command_latency_ms':100,'environment':{
        'kind':'uncalibrated_room_v1','calibration_status':'uncalibrated_synthetic',
        'source_note':'author assumptions, NOT causal calibration or realistic range',
        'parameter_reference':'docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates',
        'tick_ms':1000,'deadline_ms':360000,'horizon_ms':900000,'close_delay_ms':3000,
        'outdoor_temp_c':8,'target_temp_c':21,'target_co2_ppm':900,'co2_floor_ppm':420,
        'ventilation_rate_ppm_s':vent,'exchange_per_s':.0015,'heat_rate_c_per_s':heat,
        'heater_power_kw':2,'heat_admission':admission}}
    e['tool_catalog']=[]
    for a in e['agents']:
        a['observable_state']=['bedroom.temperature_c','bedroom.co2_ppm','devices.window','devices.heater']
    for t in e['task_stream']:
        template=t['action_template'];template['power_kw']=0;template['requires']=[]
        t['goal']='Send the requested device command; environmental goal is scored separately.'
        template['duration_ms']=2000 if t['task_id']=='bedroom_air' else 1000
        g=next(g for g in e['action_grounding'] if g['task_id']==t['task_id'])
        g.pop('effects',None);g.pop('environment_effects',None)
        g['start_effects']={};g['completion_effects']={'devices.'+g['target']:'open' if g['target']=='window' else 'enabled'}
        g['power_kw']=0;g['duration_ms']=template['duration_ms']
        a=next(a for a in e['agents'] if a['agent_id']==t['agent_id'])
        e['tool_catalog'].append(_tool(a['agent_id'],a['tools'][0],t['goal'],template['target'],template['operation'],{}))
    e['goals']=[{'path':'bedroom.co2_ppm','op':'lte','value':900},
                {'path':'bedroom.temperature_c','op':'gte','value':21},
                {'path':'devices.window','op':'eq','value':'closed'}]
    e['calibration']={'status':'uncalibrated_synthetic','physical_parameters_verified':False}
    e['task_card']={'family':'C2 shared environment, soft losses NOT safety violation',
                    'information':'both scripted arms have identical local room and actuator information',
                    'control':'only initial CO2 1600/850 changes ventilation need; only heat_admission changes scheduling rule',
                    'controller':'automatic closure and ideal thermostat are deterministic, not LLM decisions',
                    'physics_limits':'constant linear CO2 removal; no occupant source, closed-window leakage, heat capacity identification, or real switching model',
                    'not_claimed':'24 independent homes, device calibration, human review, or agent superiority'}
    return e


def compact_intervals(intervals,protected):
    rows=[]
    sums=('heater_on_equivalent_s','heater_energy_wh','open_window_heater_wh','ventilation_temperature_loss_c','temperature_shortfall_c_s','co2_excess_ppm_s')
    for x in intervals:
        if (rows and rows[-1]['end_ms'] not in protected
                and x['end_ms']-rows[-1]['start_ms']<=10000
                and all(rows[-1][k]==x[k] for k in ('window_open','heater_enabled'))):
            prev=rows[-1]
            prev['end_ms']=x['end_ms'];prev['temperature_end_c']=x['temperature_end_c'];prev['co2_end_ppm']=x['co2_end_ppm']
            for k in sums:prev[k]+=x[k]
        else:rows.append(deepcopy(x))
    return rows


def run(e,representative=False,provider=None):
    trace,result=run_event_simulation(e,provider or ConditionalProposals(),'ConstraintCoordinator','',shared_safety_gate=True)
    physical=result['environment']
    checked=audit(e,trace,physical)
    row={'episode_id':e['episode_id'],'environment':physical,'audit':checked,
         'command_completed':result['task_correct_action_completed'],
         'command_completion_latency_ms':result['task_completion_latency_ms'],
         'no_ventilation_needed':e['initial_state']['values']['bedroom']['co2_ppm']<=900}
    if representative:
        filtered=[x for x in trace['events'] if not (x['type']=='state_update' and x.get('source')=='synthetic_environment')]
        row['replay']={'events':filtered,'intervals':compact_intervals(trace['environment_intervals'],
            {physical['deadline_ms'],physical['first_joint_goal_observed_ms']}),
            'sampling_note':'actuator-homogeneous exact integrals merged to <=10s; original goal observations <=1s',
            'final_state':trace['final_state']}
    return row


def bundle():
    episodes=[episode(co2,v,h,a) for co2 in (1600,850) for v in (2.5,5.0) for h in (.015,.025,.035)
              for a in ('immediate','after_ventilation')]
    rows=[run(e,representative=(e['simulation']['environment']['heat_rate_c_per_s']==.025
                               and e['simulation']['environment']['ventilation_rate_ppm_s']==2.5)) for e in episodes]
    for i in range(0,len(rows),2):
        if episodes[i]['initial_state']['values']['bedroom']['co2_ppm']==850:
            assert rows[i]['environment']==rows[i+1]['environment']
    data={'homecoord_bench/task_revision/fixtures/room_v4_inputs.json':{'status':'uncalibrated_synthetic_development','episodes':episodes},
          'homecoord_bench/results/room_v4_offline_20261001.json':{'api_calls':0,'heldout_content_read':0,
              'parameter_worlds':12,'rule_runs':24,'representative_replays':4,
              'status':'synthetic_interface_and_sensitivity_not_physical_or_model_evidence','rows':rows}}
    names=('room_environment.py','room_pilot.py','room_audit.py','event_simulator_v4.py')
    data['homecoord_bench/task_revision/fixtures/room_v4_manifest.json']={
        'source_sha256':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names},
        'input_sha256':hashlib.sha256((json.dumps(data[next(iter(data))],ensure_ascii=False,indent=2)+'\n').encode()).hexdigest(),
        'migration':'explicit v4 port; prior versions/snapshots unchanged','calibration_status':'uncalibrated_synthetic'}
    return data


if __name__=='__main__':
    data=bundle()
    if len(sys.argv)==1:print(json.dumps({'artifacts':list(data),'rule_runs':24,'parameter_worlds':12}))
    else:
        text=json.dumps(data[sys.argv[1]],ensure_ascii=False,indent=2)+'\n';offset=int(sys.argv[2]) if len(sys.argv)>2 else 0
        print(json.dumps({'text':text[offset:offset+18000],'next_offset':offset+18000 if len(text)>offset+18000 else None},ensure_ascii=True))
