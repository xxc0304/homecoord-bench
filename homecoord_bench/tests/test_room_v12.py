import json,hashlib,unittest
from copy import deepcopy
from homecoord_bench.task_revision.room_revision_v12 import *
from homecoord_bench.task_revision.room_audit_v12 import audit
from homecoord_bench.task_revision.room_pilot import bundle as old_bundle

class RoomV12Tests(unittest.TestCase):
    def test_low_demand_terminal_disposition_not_command_success(self):
        for a in ('immediate','after_ventilation'):
            r=run(episode(850,admission=a));v=r['result'];tid='bedroom_air'
            self.assertTrue(v['task_admission_legal'][tid]);self.assertTrue(v['task_correct_disposition'][tid])
            self.assertEqual('satisfied_without_actuation',v['task_disposition'][tid])
            self.assertEqual(300,v['task_disposition_latency_ms'][tid]);self.assertTrue(v['task_disposition_deadline_met'][tid])
            self.assertFalse(v['task_correct_action_completed'][tid]);self.assertIsNone(v['task_completion_latency_ms'][tid])
            self.assertFalse(v['task_deadline_met'][tid])
            self.assertFalse(any(x['type'] in ('action_started','action_completed') and x.get('task_id')==tid for x in r['trace']['events']))

    def test_high_demand_skip_is_not_valid_disposition(self):
        for a in ('immediate','after_ventilation'):
            r=run(episode(admission=a),'always_skip')
            self.assertFalse(r['result']['task_correct_disposition']['bedroom_air'])
            self.assertIsNone(r['result']['task_disposition_latency_ms']['bedroom_air'])
            self.assertFalse(r['result']['environment']['joint_goal_by_deadline'])
            self.assertIsNone(r['result']['environment']['first_joint_goal_observed_ms'])

    def test_unnecessary_open_rejected_even_if_environment_goal_succeeds(self):
        for a in ('immediate','after_ventilation'):
            r=run(episode(850,admission=a),'always_open')
            self.assertFalse(r['result']['task_admission_legal']['bedroom_air'])
            self.assertFalse(r['result']['task_correct_disposition']['bedroom_air'])
            self.assertTrue(r['result']['environment']['joint_goal_by_deadline'])
            self.assertEqual(['ventilation_not_needed'],[x['reason'] for x in r['trace']['events'] if x['type']=='action_rejected'])
            self.assertEqual('closed',r['trace']['final_state']['devices']['window'])

    def test_threshold_inclusive_900_and_above_901(self):
        for c,skip in ((900,True),(901,False)):
            r=run(episode(c))
            self.assertEqual(skip,'bedroom_air' in r['audit']['skipped_without_command'])

    def test_high_commands_not_environment_service_or_on_time_goal(self):
        r=run(episode(admission='after_ventilation'))
        self.assertTrue(all(r['result']['task_correct_action_completed'].values()))
        self.assertTrue(all(r['result']['task_disposition_deadline_met'].values()))
        self.assertFalse(r['result']['environment']['joint_goal_by_deadline'])
        self.assertEqual(572000,r['result']['environment']['first_joint_goal_observed_ms'])

    def test_rule_pair_inputs_equal_and_no_private_answer_channels(self):
        a=run(episode())['calls'];b=run(episode(admission='after_ventilation'))['calls']
        self.assertEqual(a,b)
        for x in a:
            self.assertEqual('HC-M06',x['request']['episode_id'])
            self.assertNotIn('action_template',x['request']['task'])
            self.assertNotIn('required_action',x['request']['task'])

    def test_private_metadata_canary_not_in_input(self):
        e=episode(850);a=run(e)['calls'];e['episode_id']='CANARY_FUTURE_WINDOW'
        e['task_card']['hidden']='CANARY_NEXT_EVENT';e['review_status']='CANARY'
        b=run(e)['calls'];self.assertEqual(a,b)

    def test_common_controller_authority_and_closure_latency(self):
        r=run(episode());ev=r['trace']['events']
        q=next(x for x in ev if x['type']=='automatic_window_close_requested')
        ack=next(x for x in ev if x['type']=='state_update' and x.get('source')=='automatic_window_close')
        self.assertEqual(3000,ack['timestamp_ms']-q['timestamp_ms'])
        for key in ('controller_authority','close_delay_ms'):
            e=episode()
            if key=='controller_authority':e[key]['thermostat']['switching_cost_wh']=1
            else:e['simulation']['environment'][key]=2000
            with self.assertRaises(ValueError):run(e)

    def test_same_horizon_energy_tradeoff_and_low_equality(self):
        low=[run(episode(850,admission=a))['result']['environment'] for a in ('immediate','after_ventilation')]
        self.assertEqual(low[0],low[1])
        high=[run(episode(admission=a))['result']['environment'] for a in ('immediate','after_ventilation')]
        self.assertLess(high[0]['first_joint_goal_observed_ms'],high[1]['first_joint_goal_observed_ms'])
        self.assertGreater(high[0]['horizon_integrals']['heater_energy_wh'],high[1]['horizon_integrals']['heater_energy_wh'])
        self.assertEqual(900000,high[0]['common_horizon_ms'])

    def test_tampered_disposition_and_skip_cannot_pass_audit(self):
        e=episode();r=run(e);bad=deepcopy(r['trace'])
        bad['events'].insert(2,{'type':'request_satisfied_without_actuation','timestamp_ms':300,'task_id':'bedroom_air'})
        with self.assertRaises(AssertionError):audit(e,bad,r['result'],r['calls'])
        e=episode(850);r=run(e);bad=deepcopy(r['result']);bad['task_correct_action_completed']['bedroom_air']=True
        with self.assertRaises(AssertionError):audit(e,r['trace'],bad,r['calls'])

    def test_all_32_saved_full_traces_and_hashes_reproduce(self):
        b=bundle();count=0
        for p,v in b.items():
            self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
            if 'trace_encoding' in v:
                row=unpack(v);audit(next(e for e in b[OUT+'/inputs.json']['episodes'] if e['episode_id']==row['trace']['episode_id']) if '/runs/' in p else next(x['episode'] for x in b[OUT+'/inputs.json']['diagnostics'] if x['case']+'-'+x['episode']['simulation']['environment']['heat_admission']+'.json'==p.split('/')[-1]),row['trace'],row['result'],row['calls'])
                count+=1
        self.assertEqual(32,count)
        for p,h in b[OUT+'/manifest.json']['source_sha256'].items():self.assertEqual(h,hashlib.sha256((ROOT/p).read_bytes()).hexdigest())

    def test_frozen_v4_material_unchanged(self):
        for p,v in old_bundle().items():self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
