import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from homecoord_bench.task_revision import f2_reservation_ablation_v1 as exp
from homecoord_bench.task_revision.f2_revision import PublicProposals
from homecoord_bench.task_revision.small_validation_plan_v1 import variant


class ReservationAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = exp.read(exp.PLAN)
        cls.documents = [exp.read(exp.config_path(i)) for i in range(8)]

    def test_locked_grid_and_old_materials(self):
        lock = exp.verify_lock()
        self.assertEqual(exp.static_plan(), self.plan)
        self.assertEqual((8, 16, 8, 24), tuple(self.plan['scope'][k] for k in
                         ('configurations', 'runs', 'pairs', 'information_diagnostic_runs')))
        self.assertGreater(len(lock['protected_sha256']), 100)

    def test_all_saved_inputs_and_pair_statistics_recount(self):
        for config, doc in zip(self.plan['configurations'], self.documents):
            self.assertEqual(exp.episode_for(config), doc['input'])
            self.assertEqual(exp.pair_audit(doc['input'], doc['runs']), doc['pair'])

    def test_four_historical_baselines_complete_exact_reproduction(self):
        rows = [d for d in self.documents if d['config']['role'] == 'primary']
        self.assertEqual(4, len(rows))
        for d in rows:
            self.assertEqual(exp.exact_historical(d['config'], d['runs'][0]), d['historical_reproduction'])

    def test_shared_information_permissions_and_prefixes(self):
        for d in self.documents:
            a, b = d['runs']
            self.assertEqual(a['calls'], b['calls'])
            self.assertTrue(d['pair']['full_prefix_through_commit_equal'])
            for c in a['calls']:
                r = c['request']; now = r['current_time_ms']
                self.assertEqual('F2-public-home', r['episode_id'])
                self.assertNotIn('RA1-', json.dumps(r))
                self.assertEqual({t['task_id'] for t in d['input']['task_stream'] if t['release_at_ms'] <= now},
                                 {t['task_id'] for t in r['state']['coordination_context']['requests']})

    def test_running_services_unmodified_and_no_physical_off(self):
        for d in self.documents:
            self.assertTrue(d['pair']['running_service_intervals_unchanged'])
            for run in d['runs']:
                self.assertTrue(all(x['operation'] == 'prepare' for x in run['trace']['events']
                                    if x['type'] in ('action_started', 'action_completed')))

    def test_capacity_and_receipts_from_full_events(self):
        for d in self.documents:
            for r in d['runs']:
                a = exp.audit(d['input'], r)
                self.assertEqual(0, a['metrics']['executed_capacity_violation_duration_ms'])
                self.assertEqual(0, a['metrics']['excess_resource_unit_ms'])
                self.assertEqual(4, a['denominators']['required'])

    def test_all_invalidated_callbacks_suppressed_once(self):
        for d in self.documents:
            for run in d['runs']:
                a = exp.audit(d['input'], run)
                self.assertEqual(len(a['invalidated_reservations']), a['event_counts'].get('reservation_callback_suppressed', 0))
                if run['arm'] == 'retain': self.assertEqual([], a['invalidated_reservations'])

    def test_information_diagnostics_all_24_unique(self):
        stat = exp.statistics()
        self.assertEqual(24, len(stat['information_checks']))
        self.assertTrue(all(r['prefix_equal'] for r in stat['information_checks']))

    def test_forged_completion_generation_rejected(self):
        d = self.documents[0]; run = deepcopy(d['runs'][0])
        receipt = next(x for x in run['trace']['events'] if x['type'] == 'action_completed')
        receipt['reservation_generation'] += 1
        with self.assertRaisesRegex(ValueError, 'receipt identity'): exp.audit(d['input'], run)

    def test_forged_completion_time_rejected(self):
        d = self.documents[0]; run = deepcopy(d['runs'][0])
        receipt = next(x for x in run['trace']['events'] if x['type'] == 'action_completed')
        receipt['timestamp_ms'] -= 1
        with self.assertRaises(ValueError): exp.audit(d['input'], run)

    def test_forged_legacy_score_rejected(self):
        d = self.documents[0]; run = deepcopy(d['runs'][0])
        run['result']['task_correct_action_completed']['water'] = False
        with self.assertRaisesRegex(ValueError, 'legacy result mismatch'): exp.audit(d['input'], run)

    def test_forged_callback_disposition_rejected(self):
        d = next(d for d in self.documents if d['pair']['unstarted_task_ids'])
        run = deepcopy(d['runs'][1])
        event = next(x for x in run['trace']['events'] if x['type'] == 'reservation_callback_suppressed')
        event['reservation_generation'] = 999
        with self.assertRaisesRegex(ValueError, 'suppressed callback'): exp.audit(d['input'], run)

    def test_unequal_review_cost_or_arm_order_rejected(self):
        d = self.documents[0]; runs = deepcopy(d['runs']); runs[1]['review_delay_ms'] += 1
        with self.assertRaisesRegex(ValueError, 'unequal review'): exp.pair_audit(d['input'], runs)
        with self.assertRaisesRegex(ValueError, 'arm pairing'): exp.pair_audit(d['input'], list(reversed(d['runs'])))

    def test_changed_public_input_rejected(self):
        d = self.documents[0]; run = deepcopy(d['runs'][0])
        run['calls'][0]['request']['task']['completion_deadline_ms'] += 1
        with self.assertRaises(ValueError): exp.audit(d['input'], run)

    def test_no_action_preserves_false_null_and_zero_denominator_boundary(self):
        class NoAction(PublicProposals):
            def decide(self, request, instructions):
                decision = {'response_type': 'noop', 'actions': [], 'accepted_proposal_ids': [],
                            'rejected_proposal_ids': [], 'defer_until_ms': None, 'reason_code': 'no_applicable_action'}
                self.calls.append({'request': deepcopy(request), 'decision': deepcopy(decision)})
                return decision
        e = self.documents[0]['input']
        for arm in exp.ARMS:
            run = exp.simulate(e, arm, 0, NoAction()); a = exp.audit(e, run)
            self.assertEqual({'required': 4, 'completed': 0, 'timely': 0}, a['denominators'])
            self.assertEqual(0, a['metrics']['service_rate'])
            self.assertEqual(0, a['metrics']['timely_service_rate'])
            self.assertIsNone(a['conditional_timely_rate'])
            self.assertIsNone(a['metrics']['whole_house_completion_ms'])
            for t in a['tasks'].values():
                self.assertFalse(t['completed']); self.assertFalse(t['timely'])
                self.assertIsNone(t['completion_ms']); self.assertIsNone(t['completion_latency_ms'])

    def test_common_K_empty_preserves_fixed_E(self):
        d = self.documents[0]; a = deepcopy(d['pair']['audits'][0]); b = deepcopy(a)
        b['completed_task_ids'] = []
        value = exp.time_compare([a, b], exp.TIME_NAMES)
        self.assertEqual(4, value['required_count']); self.assertEqual(0, value['common_count'])
        self.assertFalse(value['eligible']); self.assertEqual('no_common_completed_requests', value['null_reason'])
        self.assertTrue(all(v['arm_means'] == [None, None] for v in value['metrics'].values()))

    def boundary_episode(self, water_release):
        d = next(d for d in self.documents if d['config']['template'].endswith('02')
                 and d['config']['capacity_arm'] == 'competition' and d['config']['role'] == 'primary')
        old_release = next(t['release_at_ms'] for t in d['input']['task_stream'] if t['task_id'] == 'water')
        return variant(d['input'], 'water_release_offset_ms', water_release-old_release)

    def test_commit_same_timestamp_as_start_uses_actual_phase_order(self):
        # meal completes at 180400 phase0; cleaning old start is phase4.
        for cost, release in [(0, 180100), (100, 180000)]:
            e = self.boundary_episode(release)
            runs = [exp.simulate(e, arm, cost) for arm in exp.ARMS]
            pair = exp.pair_audit(e, runs)
            self.assertEqual(180400, pair['commit_ms'])
            self.assertIn('cleaning', pair['unstarted_task_ids'])
            self.assertNotIn('cleaning', pair['running_task_ids'])

    def test_action_started_during_review_cannot_be_cancelled(self):
        e = self.boundary_episode(180050)
        pair = exp.pair_audit(e, [exp.simulate(e, arm, 100) for arm in exp.ARMS])
        self.assertEqual(180450, pair['commit_ms'])
        self.assertIn('cleaning', pair['running_task_ids'])
        self.assertNotIn('cleaning', pair['unstarted_task_ids'])

    def test_multiple_review_delays_keep_nonpreemptive_and_generation_rules(self):
        e = self.boundary_episode(180000)
        for cost in (0, 100, 500, 10000):
            pair = exp.pair_audit(e, [exp.simulate(e, arm, cost) for arm in exp.ARMS])
            self.assertTrue(pair['running_service_intervals_unchanged'])

    def test_engine_rejects_scope_and_invalid_parameters(self):
        e = self.documents[0]['input']
        for arm, cost in [('other', 0), ('retain', -1), ('replan', True)]:
            with self.assertRaises(ValueError): exp.simulate(e, arm, cost)
        with self.assertRaises(ValueError):
            exp.run_event_simulation(e, PublicProposals(), 'ConstraintCoordinator', '', shared_safety_gate=True)

    def test_no_online_oracle_or_new_model_call(self):
        with patch('homecoord_bench.task_revision.event_simulator_reservation_v1.ideal_schedule',
                   side_effect=AssertionError('offline oracle forbidden')):
            e = self.documents[0]['input']
            for arm in exp.ARMS:
                run = exp.simulate(e, arm, 0)
                self.assertEqual(4, len(run['calls']))

    def test_saved_statistics_scope_and_binding(self):
        stat = exp.statistics()
        self.assertEqual(16, stat['scope']['runs'])
        self.assertEqual(8, len(stat['configurations']))
        self.assertEqual(0, stat['api_calls'])
        self.assertIsNone(stat['independent_acceptance'])
        self.assertFalse(stat['ranking']); self.assertFalse(stat['cross_config_pooling'])


if __name__ == '__main__': unittest.main()
