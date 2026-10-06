import json,hashlib,unittest
from copy import deepcopy
from homecoord_bench.task_revision.dependency_revision_v11 import *
from homecoord_bench.task_revision.dependency_pilot import bundle as old_bundle
from homecoord_bench.task_revision.dependency_audit_v11 import audit
class DependencyV11Tests(unittest.TestCase):
    def test_all_52_captures_and_dependency_starts(self):
        for c in CONDITIONS:
            for p in POLICIES:
                r=run(episode(c),p);self.assertEqual(r['trace']['agent_requests'],[x['request'] for x in r['calls']])

    def test_infeasible_excluded_and_constructive_tight_feasible(self):
        c=certificates();self.assertTrue(c['INFEASIBLE_8000']['excluded_from_feasible_success_denominator'])
        for p in POLICIES:
            a=run(episode('INFEASIBLE_8000'),p);b=run(episode('FEASIBLE_8500'),p)
            extra=100 if p=='DeadlineAwareCoordinator' else 0
            self.assertFalse(a['result']['task_deadline_met']['dry']);self.assertEqual(extra==0,b['result']['task_deadline_met']['dry'])
            self.assertEqual(8500+extra,b['audit']['trusted_dependency_receipts_ms']['dry'])
            self.assertEqual(500+extra,a['result']['task_completion_tardiness_ms']['dry'])

    def test_fixed_restart_recovery_only_event_changes(self):
        a=episode('RESTART_NO_RESTORE');b=episode('RESTART_RESTORE')
        for x in (a,b):x.pop('episode_id');x.pop('nominal_window')
        b['exogenous_events']=[x for x in b['exogenous_events'] if x['event']!='wash_authorization_restored']
        self.assertEqual(a,b)
        for p in POLICIES:
            a=run(episode('RESTART_NO_RESTORE'),p);b=run(episode('RESTART_RESTORE'),p)
            self.assertFalse(a['result']['task_correct_action_completed']['dry']);self.assertIsNone(a['result']['task_completion_latency_ms']['dry'])
            self.assertEqual(9100,b['audit']['trusted_dependency_receipts_ms']['wash'])
            self.assertEqual(13200,b['audit']['trusted_dependency_receipts_ms']['dry'])

    def test_cancel_restore_never_revives_and_blocks_dry(self):
        for c in ('CANCEL_RESTORE','CANCEL_NO_RESTORE'):
            for p in POLICIES:
                r=run(episode(c),p)
                self.assertFalse(r['result']['task_correct_action_completed']['wash']);self.assertFalse(r['result']['task_correct_action_completed']['dry'])
                self.assertEqual(['dry'],r['result']['dependency_blocked_task_ids'])
                self.assertFalse(any(x['type']=='restart_proposed' for x in r['trace']['events']))

    def test_old_cancelled_completion_discarded_not_prerequisite(self):
        for p in POLICIES:
            r=run(episode('RESTART_RESTORE'),p)
            self.assertTrue(any(x['type']=='completion_discarded' and x['timestamp_ms']==4400+(100 if p=='DeadlineAwareCoordinator' else 0) for x in r['trace']['events']))
            self.assertEqual([9200],[x['timestamp_ms'] for x in r['trace']['events'] if x['type']=='action_started' and x['task_id']=='dry'])

    def test_natural_end_of_invalid_wash_cannot_write_washed_or_release_dry(self):
        for p in POLICIES:
            r=run(episode('STALE_NATURAL_RACE'),p)
            x=next(x for x in r['trace']['events'] if x['type']=='invalidated_action_physically_completed')
            self.assertEqual({'devices.washer':'off'},x['effects'])
            self.assertEqual(4400+(100 if p=='DeadlineAwareCoordinator' else 0),x['timestamp_ms'])
            self.assertEqual(9100,r['audit']['trusted_dependency_receipts_ms']['wash'])
            self.assertEqual([9200],[x['timestamp_ms'] for x in r['trace']['events'] if x['type']=='action_started' and x['task_id']=='dry'])

    def test_illegal_operation_rejected_300ms_and_downstream_unresolved(self):
        for p in POLICIES:
            r=run(episode('INVALID_PROPOSAL'),p)
            rejected=[x for x in r['trace']['events'] if x['type']=='action_rejected' and x.get('task_id')=='wash']
            self.assertEqual([400 if p=='DeadlineAwareCoordinator' else 300],[x['timestamp_ms'] for x in rejected])
            self.assertEqual(300,next(x for x in r['trace']['events'] if x['type']=='proposal_returned' and x['task_id']=='wash')['timestamp_ms'])
            self.assertEqual(['dry'],r['result']['dependency_waiting_task_ids'])
            self.assertIsNone(r['result']['task_completion_latency_ms']['dry'])
            self.assertEqual(2,len(r['calls']))

    def test_forged_state_not_trusted_receipt(self):
        for p in POLICIES:
            r=run(episode('FORGED_STATE'),p)
            self.assertEqual([4500+(100 if p=='DeadlineAwareCoordinator' else 0)],[x['timestamp_ms'] for x in r['trace']['events'] if x['type']=='action_started' and x['task_id']=='dry'])

    def test_inputs_do_not_contain_future_conditions_or_answers(self):
        for p in POLICIES:
            a=run(episode('RESTART_NO_RESTORE'),p)['calls'];b=run(episode('RESTART_RESTORE'),p)['calls']
            self.assertEqual(a,b)
            for x in a:self.assertEqual('HC-M12',x['request']['episode_id']);self.assertNotIn('action_template',x['request']['task'])

    def test_fake_valid_completion_rejected_by_independent_attempt_audit(self):
        e=episode('STALE_NATURAL_RACE');r=run(e);bad=deepcopy(r['trace'])
        x=next(x for x in bad['events'] if x['type']=='invalidated_action_physically_completed')
        x['type']='action_completed';x['effects'].update({'laundry.washed':True,'service.wash_completed':True})
        with self.assertRaisesRegex(AssertionError,'invalid attempt'):audit(e,bad,r['result'],r['calls'])

    def test_batch_and_world_receipts_rejected(self):
        for change in ('batch','receipt'):
            e=episode('EARLY')
            if change=='batch':e['batch_binding']['dry']='batch_2'
            else:e['exogenous_events'][0]['patch']['service.wash_completed']=True
            with self.assertRaises(ValueError):run(e)

    def test_new_reproducible_and_old_v3_unchanged(self):
        for p,v in old_bundle().items():self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
        b=bundle()
        for p,v in b.items():self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
        for p,h in b[OUT+'/manifest.json']['source_sha256'].items():self.assertEqual(h,hashlib.sha256((ROOT/p).read_bytes()).hexdigest())
if __name__=='__main__':unittest.main()
