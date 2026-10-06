import sys
import json
import math
import hashlib
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.append(str(ROOT.parent))
from homecoord_bench.task_revision.room_environment import evolve,validate,SyntheticRoom
from homecoord_bench.task_revision.room_pilot import episode,run,bundle,ConditionalProposals
from homecoord_bench.task_revision.room_audit import audit
from homecoord_bench.task_revision.event_simulator_v4 import run_event_simulation as v4
from homecoord_bench.task_revision.event_simulator_v3 import run_event_simulation as v3
from homecoord_bench.task_revision.milestone import FixedProposals,drafts
from homecoord_bench.task_revision.dependency_pilot import episode as dependency_episode,CONDITIONS
from homecoord_bench.task_revision.lifecycle_pilot import episode as lifecycle_episode


def simulation(e):
    return v4(e,ConditionalProposals(),'ConstraintCoordinator','',shared_safety_gate=True)


class RoomEnvironmentV4Tests(unittest.TestCase):
    def setUp(self):
        self.e=episode();self.p=self.e['simulation']['environment']

    def test_closed_heating_exact_units(self):
        x=evolve(17,1600,False,True,1,self.p)
        self.assertAlmostEqual(17.025,x['temperature_end_c'])
        self.assertAlmostEqual(2/3.6,x['heater_energy_wh'])
        self.assertEqual(1600,x['co2_end_ppm'])
        self.assertEqual(0,x['ventilation_temperature_loss_c'])

    def test_idle_closed_state_is_constant(self):
        x=evolve(17,1600,False,False,100,self.p)
        self.assertEqual(17,x['temperature_end_c'])
        self.assertEqual(0,x['heater_energy_wh'])
        self.assertEqual(400,x['temperature_shortfall_c_s'])
        self.assertEqual(70000,x['co2_excess_ppm_s'])

    def test_open_only_exact_cooling(self):
        x=evolve(17,1600,True,False,100,self.p)
        self.assertAlmostEqual(8+9*math.exp(-.15),x['temperature_end_c'])
        self.assertEqual(1350,x['co2_end_ppm'])
        self.assertAlmostEqual(17-x['temperature_end_c'],x['ventilation_temperature_loss_c'])

    def test_co2_floor_not_goal_clamp(self):
        x=evolve(17,1600,True,False,400,self.p)
        self.assertEqual(600,x['co2_end_ppm'])
        self.assertEqual(420,evolve(17,1600,True,False,1000,self.p)['co2_end_ppm'])

    def test_ideal_thermostat_closed_stops_energy_at_target(self):
        x=evolve(17,850,False,True,900,self.p)
        self.assertEqual(21,x['temperature_end_c'])
        self.assertEqual(160,x['heater_on_equivalent_s'])
        self.assertAlmostEqual(2000*160/3600,x['heater_energy_wh'])

    def test_open_thermostat_maintenance_has_equivalent_duty(self):
        x=evolve(21,850,True,True,10,self.p)
        self.assertEqual(21,x['temperature_end_c'])
        self.assertAlmostEqual(10*.0015*13/.025,x['heater_on_equivalent_s'])
        self.assertAlmostEqual(.195,x['ventilation_temperature_loss_c'])

    def test_zero_exchange_is_finite(self):
        self.p['exchange_per_s']=0
        x=evolve(17,1600,True,True,100,self.p)
        self.assertEqual(19.5,x['temperature_end_c'])
        self.assertEqual(0,x['ventilation_temperature_loss_c'])

    def test_closed_form_is_partition_invariant(self):
        for opened in (False,True):
            whole=evolve(17,1600,opened,True,400,self.p)
            a=evolve(17,1600,opened,True,123.4,self.p)
            b=evolve(a['temperature_end_c'],a['co2_end_ppm'],opened,True,276.6,self.p)
            for k in ('temperature_end_c','co2_end_ppm'):self.assertAlmostEqual(whole[k],b[k],places=8)
            for k in ('heater_energy_wh','temperature_shortfall_c_s','co2_excess_ppm_s','ventilation_temperature_loss_c'):
                self.assertAlmostEqual(whole[k],a[k]+b[k],places=6)

    def test_direct_port_splits_deadline_and_stops_at_horizon(self):
        room=SyntheticRoom(self.e);state=deepcopy(self.e['initial_state']['values'])
        room.advance(state,999999)
        self.assertEqual([360000,900000],[x['end_ms'] for x in room.intervals])
        self.assertEqual(360000,room.deadline['at_ms'])
        with self.assertRaises(ValueError):room.advance(state,1)

    def test_actuator_command_is_not_environment_completion(self):
        trace,result=simulation(self.e)
        completed=[x for x in trace['events'] if x['type']=='action_completed']
        self.assertEqual(2,len(completed))
        self.assertTrue(all(not any(k.startswith('bedroom.') for k in x['effects']) for x in completed))
        self.assertGreater(result['environment']['first_joint_goal_observed_ms'],max(x['timestamp_ms'] for x in completed))
        self.assertEqual(900000,trace['environment_intervals'][-1]['end_ms'])

    def test_environment_actuation_starts_after_command_completion(self):
        trace,_=simulation(self.e)
        times={x['task_id']:x['timestamp_ms'] for x in trace['events'] if x['type']=='action_completed'}
        for x in trace['environment_intervals']:
            if x['heater_enabled']:self.assertGreaterEqual(x['start_ms'],times['bedroom_heat'])
            if x['window_open']:self.assertGreaterEqual(x['start_ms'],times['bedroom_air'])

    def test_closure_delay_and_admission_are_actual_queue_events(self):
        e=episode(admission='after_ventilation');trace,result=simulation(e)
        req=next(x for x in trace['events'] if x['type']=='automatic_window_close_requested')
        closed=next(x for x in trace['events'] if x.get('source')=='automatic_window_close')
        heat=next(x for x in trace['events'] if x['type']=='action_started' and x['task_id']=='bedroom_heat')
        self.assertEqual(req['timestamp_ms']+3000,closed['timestamp_ms'])
        self.assertGreater(heat['timestamp_ms'],closed['timestamp_ms'])
        self.assertEqual(0,result['environment']['horizon_integrals']['open_window_heater_wh'])

    def test_no_vent_needed_pair_is_identical(self):
        a,b=run(episode(co2=850)),run(episode(co2=850,admission='after_ventilation'))
        self.assertEqual(a['environment'],b['environment'])
        self.assertFalse(a['command_completed']['bedroom_air'])
        self.assertTrue(a['environment']['joint_goal_by_deadline'])

    def test_rule_pair_changes_only_admission(self):
        a,b=episode(),episode(admission='after_ventilation')
        for e in (a,b):e.pop('episode_id');e['simulation']['environment'].pop('heat_admission')
        self.assertEqual(a,b)

    def test_low_high_pair_changes_only_initial_co2(self):
        a,b=episode(),episode(co2=850)
        for e in (a,b):e.pop('episode_id');e['initial_state']['values']['bedroom']['co2_ppm']=0
        self.assertEqual(a,b)

    def test_unmet_goal_preserves_null_not_fake_completion(self):
        e=episode(heat=.001);trace,r=simulation(e)
        self.assertIsNone(r['environment']['first_joint_goal_observed_ms'])
        self.assertIsNone(r['environment']['completion_tardiness_ms'])
        self.assertFalse(r['environment']['joint_goal_by_deadline'])
        self.assertTrue(all(r['task_correct_action_completed'].values()))

    def test_shorter_sensor_step_retains_same_physics(self):
        e=episode();_,a=simulation(e)
        e['simulation']['environment']['tick_ms']=500;_,b=simulation(e)
        self.assertLessEqual(abs(a['environment']['first_joint_goal_observed_ms']-b['environment']['first_joint_goal_observed_ms']),1000)

    def test_common_horizon_and_deadline_integral_monotonicity(self):
        r=run(self.e)['environment']
        self.assertEqual(900000,r['common_horizon_ms'])
        for k,value in r['horizon_integrals'].items():self.assertGreaterEqual(value+1e-7,r['deadline_state_and_integrals']['totals'][k])

    def test_invalid_parameters_rejected(self):
        for key,value in [('tick_ms',True),('tick_ms',0),('deadline_ms',360001),('close_delay_ms',-1),
                          ('heat_rate_c_per_s',0),('exchange_per_s',-1),('outdoor_temp_c',float('nan')),
                          ('heater_power_kw',float('inf')),('calibration_status','calibrated'),('source_note','')]:
            e=episode();e['simulation']['environment'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate(e)

    def test_instant_ambient_effect_rejected(self):
        self.e['action_grounding'][0]['start_effects']={'bedroom.co2_ppm':850}
        with self.assertRaises(ValueError):validate(self.e)

    def test_unsupported_coupling_rejected(self):
        for change in ('constraints','dependency','power','extra_task','actuator','forcing'):
            e=episode()
            if change=='constraints':e['constraints']=[{'unsupported':True}]
            if change=='dependency':e['task_stream'][1]['depends_on']=['bedroom_air']
            if change=='power':e['action_grounding'][0]['power_kw']=1
            if change=='extra_task':e['task_stream'].append(deepcopy(e['task_stream'][0]))
            if change=='actuator':e['action_grounding'][0]['completion_effects']={'devices.window':'closed'}
            if change=='forcing':e['exogenous_events']=[{'patch':{'bedroom.temperature_c':21}}]
            with self.subTest(change=change),self.assertRaises(ValueError):validate(e)

    def test_independent_audit_detects_tampered_metrics(self):
        trace,r=simulation(self.e)
        for key in ('first_joint_goal_observed_ms','completion_tardiness_ms'):
            bad=deepcopy(r['environment']);bad[key]+=1000
            with self.subTest(key=key),self.assertRaises(AssertionError):audit(self.e,trace,bad)
        bad=deepcopy(r['environment']);bad['deadline_state_and_integrals']['temperature_c']+=1
        with self.assertRaises(AssertionError):audit(self.e,trace,bad)

    def test_independent_audit_detects_tampered_energy_and_actuation(self):
        trace,r=simulation(self.e)
        bad=deepcopy(trace);bad['environment_intervals'][0]['heater_energy_wh']+=1
        with self.assertRaises(AssertionError):audit(self.e,bad,r['environment'])
        bad=deepcopy(trace);bad['environment_intervals'][0]['window_open']=True
        with self.assertRaises(AssertionError):audit(self.e,bad,r['environment'])

    def test_no_environment_v3_v4_parity(self):
        episodes=drafts()+[lifecycle_episode(k,c) for k in ('CLEAN','RAIN') for c in ('NOEVENT','PRESTART','INFLIGHT','POSTCOMPLETE','UNRELATED')]+[dependency_episode(c) for c in CONDITIONS]
        # Existing versioned milestones remain authoritative, with no environment.
        for e in episodes:
            for p in ('IndependentMultiAgent','ConstraintCoordinator','GateRetryRule','DeadlineAwareCoordinator'):
                args=(e,FixedProposals(),p,'')
                self.assertEqual(v3(*args,shared_safety_gate=True),v4(*args,shared_safety_gate=True))

    def test_saved_sources_and_inputs_match_manifest(self):
        manifest=json.loads((ROOT/'task_revision/fixtures/room_v4_manifest.json').read_text(encoding='utf-8'))
        for name,digest in manifest['source_sha256'].items():
            self.assertEqual(digest,hashlib.sha256((ROOT/'task_revision'/name).read_bytes()).hexdigest())
        self.assertEqual(manifest['input_sha256'],hashlib.sha256((ROOT/'task_revision/fixtures/room_v4_inputs.json').read_bytes()).hexdigest())

    def test_saved_results_reproduce_all_24_runs(self):
        data=bundle()
        for name,expected in data.items():self.assertEqual(expected,json.loads((ROOT.parent/name).read_text(encoding='utf-8')))


if __name__=='__main__':unittest.main()
