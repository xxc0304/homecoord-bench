import sys
import json
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT.parent))
from homecoord_bench.task_revision.lifecycle_pilot import episode, run, bundle
from homecoord_bench.task_revision.lifecycle_audit import audit
from homecoord_bench.task_revision.milestone import drafts, FixedProposals
from homecoord_bench.task_revision.event_simulator_v2 import run_event_simulation as v2
from runtime.event_simulator import run_event_simulation as v1
from probe_architecture_comparison_20261001 import locked
from probe_c3_multimode_20260930 import PublicModeClient


def events(r, kind, tid=None):
    return [x for x in r['trace']['events'] if x['type'] == kind and (tid is None or x.get('task_id') == tid)]


class LifecycleV2Tests(unittest.TestCase):
    def test_disabled_feature_matches_v1_all_prior_semantics_inputs(self):
        for e in drafts():
            for p in ('IndependentMultiAgent','ConstraintCoordinator','GateRetryRule','DeadlineAwareCoordinator'):
                with self.subTest(e=e['episode_id'], policy=p):
                    self.assertEqual(v1(e,FixedProposals(),p,'',shared_safety_gate=True),
                                     v2(e,FixedProposals(),p,'',shared_safety_gate=True))

    def test_old_architecture_hash_lock_stays_valid(self):
        _, inputs = locked()
        self.assertEqual(12, len(inputs))

    def test_disabled_feature_matches_v1_existing_c3_development(self):
        paths = sorted((ROOT / 'revision_drafts/20260930_task_family_split/development').glob('*.json'))
        self.assertEqual(24,len(paths))
        for path in paths:
            e = json.loads(path.read_text(encoding='utf-8'))
            latencies = {t['task_id']:300 for t in e['task_stream']}
            for p in ('IndependentMultiAgent','ConstraintCoordinator','GateRetryRule','DeadlineAwareCoordinator'):
                with self.subTest(e=e['episode_id'],policy=p):
                    self.assertEqual(v1(e,PublicModeClient('prepare',latencies),p,'',shared_safety_gate=True),
                                     v2(e,PublicModeClient('prepare',latencies),p,'',shared_safety_gate=True))

    def test_stop_does_not_immediately_remove_harm(self):
        e = episode('CLEAN','INFLIGHT')
        r = run(e)
        self.assertEqual(1000, events(r,'stop_requested')[0]['timestamp_ms'])
        self.assertEqual(1200, events(r,'action_stopped')[0]['timestamp_ms'])
        self.assertEqual(200, r['metrics']['harm_duration_ms'])
        self.assertFalse(r['metrics']['zero_harm'])
        self.assertEqual(200, next(iter(r['metrics']['stop_latency_ms'].values())))

    def test_clean_restart_full_duration_not_old_completion(self):
        e = episode('CLEAN','INFLIGHT')
        tid = e['task_stream'][0]['task_id']
        r = run(e)
        self.assertEqual([400,5100], [x['timestamp_ms'] for x in events(r,'action_started',tid)])
        self.assertEqual([8100], [x['timestamp_ms'] for x in events(r,'action_completed',tid)])
        self.assertEqual([3400], [x['timestamp_ms'] for x in events(r,'completion_discarded',tid)])
        self.assertTrue(r['metrics']['recovery_completed'][tid])
        self.assertEqual(8100, r['metrics']['completion_latency_ms'][tid])

    def test_rain_withdrawal_not_irrigation_completion(self):
        e = episode('RAIN','INFLIGHT')
        tid = e['task_stream'][0]['task_id']
        r = run(e)
        self.assertFalse(r['metrics']['action_completed'][tid])
        self.assertTrue(r['metrics']['resolution_correct'][tid])
        self.assertIsNone(r['metrics']['completion_latency_ms'][tid])
        self.assertIsNone(r['metrics']['recovery_completed'][tid])
        self.assertFalse(r['trace']['final_state']['service']['work_completed'])
        self.assertEqual([], events(r,'restart_proposed'))

    def test_unnecessary_baseline_irrigation_completion_not_correct_resolution(self):
        e = episode('RAIN','INFLIGHT')
        r = run(e,enabled=False)
        tid = e['task_stream'][0]['task_id']
        self.assertTrue(r['metrics']['action_completed'][tid])
        self.assertFalse(r['metrics']['resolution_correct'][tid])

    def test_prestart_clean_recovers_rain_does_not_start(self):
        clean, rain = episode('CLEAN','PRESTART'), episode('RAIN','PRESTART')
        a, b = run(clean), run(rain)
        tid = clean['task_stream'][0]['task_id']
        self.assertEqual([5100], [x['timestamp_ms'] for x in events(a,'action_started',tid)])
        self.assertEqual(0, a['metrics']['harm_duration_ms'])
        self.assertTrue(a['metrics']['recovery_completed'][tid])
        self.assertEqual([], events(b,'action_started',rain['task_stream'][0]['task_id']))
        self.assertTrue(b['metrics']['resolution_correct'][rain['task_stream'][0]['task_id']])

    def test_exact_start_event_rejects_before_device_moves(self):
        e = episode('CLEAN','PRESTART')
        e['exogenous_events'][0]['at_ms'] = 400
        r = run(e)
        self.assertEqual(0, r['metrics']['harm_duration_ms'])
        self.assertEqual([], events(r,'stop_requested'))

    def test_exact_completion_event_natural_finish_wins(self):
        for kind in ('CLEAN','RAIN'):
            e = episode(kind,'INFLIGHT')
            e['exogenous_events'][0]['at_ms'] = 3400
            r = run(e)
            self.assertEqual([], events(r,'stop_requested'))
            self.assertEqual(0, r['metrics']['harm_duration_ms'])
            self.assertTrue(r['metrics']['action_completed'][e['task_stream'][0]['task_id']])

    def test_ack_equal_completion_is_too_late_not_cancellation(self):
        e = episode('RAIN','INFLIGHT',delay=200)
        e['exogenous_events'][0]['at_ms'] = 3200
        r = run(e)
        self.assertEqual(1, r['metrics']['stop_ack_too_late_count'])
        self.assertEqual([], events(r,'action_stopped'))
        self.assertEqual(200, r['metrics']['harm_duration_ms'])
        self.assertFalse(r['metrics']['resolution_correct'][e['task_stream'][0]['task_id']])
        self.assertIsNone(next(iter(r['metrics']['stop_latency_ms'].values())))

    def test_ack_after_completion_never_overwrites_receipt(self):
        e = episode('RAIN','INFLIGHT',delay=3000)
        r = run(e)
        self.assertEqual(1, r['metrics']['stop_ack_too_late_count'])
        self.assertTrue(r['trace']['final_state']['service']['work_completed'])
        self.assertEqual([], events(r,'completion_invalidated'))

    def test_duplicate_invalid_events_request_one_stop(self):
        e = episode('CLEAN','INFLIGHT')
        extra = deepcopy(e['exogenous_events'][0])
        extra['at_ms'] = 1050
        e['exogenous_events'].append(extra)
        r = run(e)
        self.assertEqual(1,len(events(r,'stop_requested')))
        self.assertEqual(1,len(events(r,'action_stopped')))

    def test_zero_delay_stop_zero_positive_duration_harm(self):
        e = episode('RAIN','INFLIGHT',delay=0)
        r = run(e)
        self.assertEqual(0,r['metrics']['harm_duration_ms'])
        self.assertEqual(1000,events(r,'action_stopped')[0]['timestamp_ms'])

    def test_clear_before_ack_does_not_restart_while_old_action_active(self):
        e = episode('CLEAN','INFLIGHT')
        e['exogenous_events'][1]['at_ms'] = 1100
        r = run(e)
        tid = e['task_stream'][0]['task_id']
        self.assertEqual([400,1300], [x['timestamp_ms'] for x in events(r,'action_started',tid)])
        self.assertEqual(100, r['metrics']['harm_duration_ms'])

    def test_two_cancellations_two_unique_restarts(self):
        e = episode('CLEAN','INFLIGHT')
        enter, leave = deepcopy(e['exogenous_events'][0]), deepcopy(e['exogenous_events'][1])
        enter['at_ms'], leave['at_ms'] = 5500,6000
        e['exogenous_events'] += [enter,leave]
        r = run(e)
        self.assertEqual(2,len(events(r,'action_stopped')))
        self.assertEqual(2,r['metrics']['restart_count'])
        starts = events(r,'action_started',e['task_stream'][0]['task_id'])
        self.assertEqual(3,len({x['proposal_id'] for x in starts}))
        self.assertEqual(400,r['metrics']['harm_duration_ms'])

    def test_never_clear_reports_failed_recovery_not_fake_completion(self):
        e = episode('CLEAN','INFLIGHT')
        e['exogenous_events'] = e['exogenous_events'][:1]
        tid = e['task_stream'][0]['task_id']
        r = run(e)
        self.assertFalse(r['metrics']['recovery_completed'][tid])
        self.assertFalse(r['metrics']['resolution_correct'][tid])
        self.assertIsNone(r['metrics']['completion_latency_ms'][tid])

    def test_rain_clear_does_not_unwithdraw_request(self):
        e = episode('RAIN','INFLIGHT')
        clear = deepcopy(e['exogenous_events'][0])
        clear['at_ms'] = 1500
        clear['patch'] = {p:False for p in clear['patch']}
        e['exogenous_events'].append(clear)
        r = run(e)
        self.assertEqual([],events(r,'restart_proposed'))
        self.assertTrue(r['metrics']['resolution_correct'][e['task_stream'][0]['task_id']])

    def test_release_capacity_on_ack_not_old_finish(self):
        e = episode('CLEAN','INFLIGHT')
        e['home']['resources']['max_power_kw'] = .2
        e['conflict_rules'].append({'type':'C3','capacity':.2})
        monitor = e['task_stream'][1]
        monitor['release_at_ms'] = 400
        monitor['action_template']['power_kw'] = .2
        monitor['action_template']['duration_ms'] = 500
        ground = e['action_grounding'][1]
        ground['power_kw'], ground['duration_ms'] = .2,500
        r = run(e,'GateRetryRule')
        # Capacity is free at ack=1200; the retry still pays its 100ms command.
        self.assertEqual([1300],[x['timestamp_ms'] for x in events(r,'action_started',monitor['task_id'])])
        self.assertEqual(0,r['metrics']['active_reservations_at_end'])

    def test_recovery_rechecks_condition_after_restart_queued(self):
        e = episode('CLEAN','INFLIGHT')
        c = e['simulation']['lifecycle_contracts'][e['task_stream'][0]['task_id']]
        c['restart_delay_ms'] = 100
        again = deepcopy(e['exogenous_events'][0])
        again['at_ms'] = 5050
        e['exogenous_events'].append(again)
        r = run(e)
        self.assertEqual([],events(r,'restart_proposed'))
        self.assertFalse(r['metrics']['recovery_completed'][e['task_stream'][0]['task_id']])

    def test_contract_forbids_service_receipt_in_stop_effects(self):
        e = episode('CLEAN','INFLIGHT')
        e['simulation']['lifecycle_contracts'][e['task_stream'][0]['task_id']]['stop_effects']['service.work_completed'] = True
        with self.assertRaises(ValueError): run(e)

    def test_contract_rejects_unobservable_validity_and_negative_delay(self):
        for mutation in ('invisible','negative','boolean'):
            e = episode('CLEAN','INFLIGHT')
            c = e['simulation']['lifecycle_contracts'][e['task_stream'][0]['task_id']]
            if mutation == 'invisible': c['valid_when'][0]['path'] = 'secret.occupied'
            else: c['stop_ack_delay_ms'] = -1 if mutation == 'negative' else True
            with self.assertRaises(ValueError): run(e)

    def test_restart_uses_same_owner_permission_and_fresh_version(self):
        e = episode('CLEAN','INFLIGHT')
        r = run(e)
        restart = events(r,'restart_proposed')[0]
        action = events(r,'action_started',e['task_stream'][0]['task_id'])[-1]
        self.assertEqual(restart['state_version'],action['based_on_state_version'])
        self.assertEqual(e['task_stream'][0]['agent_id'],action['agent_id'])
        self.assertEqual(0,restart['additional_model_calls'])

    def test_independent_audit_rejects_cancelled_ghost_completion(self):
        e = episode('RAIN','INFLIGHT')
        r = run(e)
        ghost = deepcopy(events(r,'action_started',e['task_stream'][0]['task_id'])[0])
        ghost.update(type='action_completed', timestamp_ms=3400, effects={'service.work_completed':True})
        trace = deepcopy(r['trace'])
        trace['events'].append(ghost)
        trace['events'].sort(key=lambda x:x['timestamp_ms'])
        with self.assertRaises(AssertionError): audit(e,trace,r['metrics'])

    def test_independent_audit_rejects_harm_masking(self):
        e = episode('CLEAN','INFLIGHT')
        r = run(e)
        wrong = deepcopy(r['metrics'])
        wrong['harm_duration_ms'] = 0
        with self.assertRaises(AssertionError): audit(e,r['trace'],wrong)

    def test_event_and_stop_delay_grid_half_open_execution_interval(self):
        for kind in ('CLEAN','RAIN'):
            for at in (1,399,400,401,1000,3200,3399,3400,3401,4000):
                for delay in (0,1,100,200,2400,3000):
                    with self.subTest(kind=kind,at=at,delay=delay):
                        e = episode(kind,'INFLIGHT',delay=delay)
                        e['exogenous_events'][0]['at_ms'] = at
                        r = run(e)
                        expected = min(delay,3400-at) if 400 < at < 3400 else 0
                        self.assertEqual(expected,r['metrics']['harm_duration_ms'])
                        self.assertEqual(int(400 < at < 3400 and at+delay < 3400),r['metrics']['stop_confirmed_count'])

    def test_action_deadline_not_met_by_cancelled_old_attempt(self):
        e = episode('CLEAN','INFLIGHT')
        tid = e['task_stream'][0]['task_id']
        e['task_stream'][0]['completion_deadline_ms'] = 6000
        trace, result = v2(e,FixedProposals(),'IndependentMultiAgent','',shared_safety_gate=True)
        self.assertEqual(8100,result['task_action_finish_time_ms'][tid])
        self.assertFalse(result['task_deadline_met'][tid])
        self.assertFalse(result['all_deadlines_met'])
        self.assertEqual(2100,result['task_completion_tardiness_ms'][tid])

    def test_cancelled_irrigation_not_in_legacy_service_count(self):
        e = episode('RAIN','INFLIGHT')
        _, result = v2(e,FixedProposals(),'IndependentMultiAgent','',shared_safety_gate=True)
        self.assertEqual(1,result['served_task_count'])
        self.assertEqual(.5,result['task_service_rate'])
        self.assertFalse(result['task_service'][e['task_stream'][0]['task_id']])

    def test_independent_audit_rejects_fake_stop_latency(self):
        e = episode('RAIN','INFLIGHT')
        r = run(e)
        wrong = deepcopy(r['metrics'])
        wrong['stop_latency_ms'] = {k:0 for k in wrong['stop_latency_ms']}
        with self.assertRaises(AssertionError): audit(e,r['trace'],wrong)

    def test_saved_pilot_matches_recomputed_offline_data(self):
        for rel, expected in bundle().items():
            with self.subTest(file=rel):
                self.assertEqual(expected,json.loads((ROOT.parent / rel).read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
