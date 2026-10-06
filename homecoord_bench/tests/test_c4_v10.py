import hashlib,json,unittest
from copy import deepcopy
from homecoord_bench.task_revision.c4_revision_v10 import run,cases,bundle,ROOT,OUT,serialize,episode,POLICIES
from homecoord_bench.task_revision.c4_audit_v10 import audit

class C4V10Tests(unittest.TestCase):
    def case(self,name):return next(x['episode'] for x in cases() if x['case']==name)

    def test_late_race_all_policies_recover_with_new_valid_attempt(self):
        e=self.case('late_race');tid=e['task_stream'][0]['task_id']
        for p in POLICIES:
            r=run(e,p);ev=r['trace']['events']
            self.assertEqual([400,5100],[x['timestamp_ms'] for x in ev if x['type']=='action_started' and x['task_id']==tid])
            self.assertEqual([8100],[x['timestamp_ms'] for x in ev if x['type']=='action_completed' and x['task_id']==tid])
            old=next(x for x in ev if x['type']=='invalidated_action_physically_completed')
            self.assertEqual(3400,old['timestamp_ms']);self.assertNotIn('service.work_completed',old['effects'])
            self.assertEqual(8100,r['result']['task_completion_latency_ms'][tid])
            self.assertNotEqual(old['proposal_id'],next(x for x in ev if x['type']=='action_completed' and x['task_id']==tid)['proposal_id'])

    def test_before_recovery_all_policies_false_null_and_no_goal_success(self):
        e=self.case('late_race');e['exogenous_events']=[x for x in e['exogenous_events'] if x['at_ms']<=4000]
        tid=e['task_stream'][0]['task_id']
        for p in POLICIES:
            r=run(e,p)
            self.assertFalse(r['result']['task_correct_action_completed'][tid])
            self.assertIsNone(r['result']['task_completion_latency_ms'][tid])
            self.assertIsNone(r['result']['task_completion_tardiness_ms'][tid])
            self.assertFalse(r['result']['task_deadline_met'][tid])
            self.assertFalse(r['trace']['final_state']['service']['work_completed'])
            self.assertEqual(400,r['result']['task_start_wait_ms'][tid])

    def test_no_restore_never_fake_success(self):
        e=self.case('never_restore');tid=e['task_stream'][0]['task_id']
        for p in POLICIES:
            r=run(e,p);self.assertEqual('pending_validity',r['audit']['request_disposition'][tid])
            self.assertFalse(r['result']['task_correct_action_completed'][tid]);self.assertIsNone(r['result']['task_completion_latency_ms'][tid])

    def test_restoration_before_natural_end_does_not_revalidate_old_attempt(self):
        e=self.case('restore_before_natural_end');tid=e['task_stream'][0]['task_id']
        for p in POLICIES:
            r=run(e,p)
            self.assertEqual(6500,r['result']['task_completion_latency_ms'][tid])
            self.assertEqual([3400],[x['timestamp_ms'] for x in r['trace']['events'] if x['type']=='invalidated_action_physically_completed'])
            self.assertEqual([3500],[x['timestamp_ms'] for x in r['trace']['events'] if x['type']=='action_started' and ':restart:' in x['proposal_id']])
            self.assertEqual(300,r['audit']['response_records'][0]['actual_invalid_running_exposure_ms'])
            self.assertTrue(any(x['type']=='stop_ack_too_late' and x['timestamp_ms']==4000 for x in r['trace']['events']))

    def test_right_open_boundary_before_equal_after_all_policies(self):
        for name,expected in [('just_before_end',8100),('exact_boundary',3400),('just_after_end',3400)]:
            e=self.case(name);tid=e['task_stream'][0]['task_id']
            for p in POLICIES:
                r=run(e,p);self.assertEqual(expected,r['result']['task_completion_latency_ms'][tid])
                self.assertEqual(name=='just_before_end',bool(r['audit']['physical_completions_after_invalidation']))

    def test_physical_exposure_preserved_and_no_extra_model_calls(self):
        for p in POLICIES:
            r=run(self.case('late_race'),p);s=r['audit']['response_records'][0]
            self.assertEqual(400,s['actual_invalid_running_exposure_ms']);self.assertEqual(200,s['extra_exposure_beyond_tolerance_ms'])
            self.assertFalse(s['stop_confirmed']);self.assertFalse(s['quiescence_timely']);self.assertTrue(s['request_timely'])
            self.assertEqual(2,len(r['calls']))
            self.assertTrue(all(x['additional_model_calls']==0 for x in r['trace']['events'] if x['type']=='restart_proposed'))

    def test_new_recount_rejects_original_four_v9_false_completions(self):
        path=ROOT/'homecoord_bench/task_revision/fixtures/c4_v9/diagnostics/C4R1-CLEAN-LATE-late_natural_race.json'
        for r in json.loads(path.read_text(encoding='utf-8'))['runs']:
            with self.assertRaisesRegex(AssertionError,'invalid attempt'):
                audit(episode('CLEAN','LATE',1000),r['trace'],r['result'],r['calls'])

    def test_audit_rejects_tampered_physical_event_as_service(self):
        e=self.case('late_race');r=run(e);bad=deepcopy(r['trace'])
        x=next(x for x in bad['events'] if x['type']=='invalidated_action_physically_completed')
        x['type']='action_completed';x['effects']['service.work_completed']=True
        with self.assertRaisesRegex(AssertionError,'invalid attempt'):audit(e,bad,r['result'],r['calls'])

    def test_92_unaffected_results_and_96_inputs_match_old(self):
        b=bundle();g=b[OUT+'/regression.json']
        self.assertEqual(92,sum(x['result_equal'] for x in g['checks']))
        self.assertTrue(all(x['input_capture_equal'] for x in g['checks']))

    def test_saved_material_and_v9_freeze(self):
        b=bundle()
        for p,v in b.items():self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
        for group in ('source_sha256','v9_frozen_sha256'):
            for p,h in b[OUT+'/manifest.json'][group].items():self.assertEqual(h,hashlib.sha256((ROOT/p).read_bytes()).hexdigest())

if __name__=='__main__':unittest.main()
