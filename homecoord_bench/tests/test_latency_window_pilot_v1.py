"""Static design tests and read-only saved-trajectory checks. No new simulations."""
import unittest
from copy import deepcopy

from homecoord_bench.task_revision import latency_window_pilot_v1 as exp
from homecoord_bench.task_revision import latency_window_crosscheck_v1 as cross


class StaticLatencyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = exp.build_plan()

    def test_scope_44_88_24_no_blind_test_claim(self):
        self.assertEqual(44, len(self.plan['configurations']))
        self.assertEqual(8, len(self.plan['worlds']))
        self.assertEqual(88, self.plan['scope']['formal_runs'])
        self.assertEqual(24, self.plan['scope']['information_diagnostic_runs'])
        self.assertFalse(self.plan['blind_test'])
        self.assertFalse(self.plan['independent_structures_claimed'])

    def test_exact_delay_grid_and_known_prior_tests(self):
        for w in self.plan['worlds']:
            ds = tuple(c['review_delay_ms'] for c in self.plan['configurations'] if c['world_id'] == w['world_id'])
            self.assertEqual(exp.ORIGINAL_DELAYS if w['arrival_regime'] == 'original' else exp.NEAR_DELAYS, ds)
        self.assertTrue(self.plan['known_prior_boundary_tests'])
        self.assertFalse(self.plan['predictions_use_new_performance_runs'])

    def test_world_input_changes_and_own_budgets(self):
        for w in self.plan['worlds']:
            e = exp.input_for(w)
            source = next(s for s in exp.source_rows() if s['episode_id'] == w['source_episode_id'])
            for a, b in zip(source['task_stream'], e['task_stream']):
                self.assertEqual(a['completion_deadline_ms']-a['release_at_ms'], b['completion_deadline_ms']-b['release_at_ms'])
            self.assertEqual(e['action_grounding'], source['action_grounding'])
            self.assertEqual(e['simulation'], source['simulation'])

    def test_near_margins_match_both_capacities_but_only_tight_active(self):
        near = [w for w in self.plan['worlds'] if w['arrival_regime'] == 'near_start']
        self.assertEqual(4, len(near))
        for w in near:
            self.assertEqual(2000, w['matched_tight_revocation_margin_ms'])
            self.assertEqual(1900, w['matched_tight_absorption_margin_ms'])
            self.assertEqual(w['capacity_arm'] == 'competition', w['margin_is_active'])

    def test_all_worlds_offline_feasible_not_online_oracle(self):
        for w in self.plan['worlds']:
            self.assertEqual('constructive_schedule_found', w['feasibility']['status'])
            self.assertEqual('offline_all_requests_not_online_input_or_baseline', w['feasibility']['information'])

    def test_prediction_same_tick_and_after_tick_differ_without_running_engine(self):
        for w in self.plan['worlds']:
            if w['arrival_regime'] != 'near_start' or w['capacity_arm'] != 'competition':
                continue
            before, after = [next(c for c in self.plan['configurations'] if c['world_id'] == w['world_id']
                                  and c['review_delay_ms'] == d)['prediction'] for d in (2000, 2001)]
            self.assertIn(w['blocker_task_id'], before['expected_unstarted_task_ids'])
            self.assertNotIn(w['blocker_task_id'], before['expected_running_task_ids'])
            self.assertIn(w['blocker_task_id'], after['expected_running_task_ids'])
            self.assertNotIn(w['blocker_task_id'], after['expected_unstarted_task_ids'])

    def test_interval_fit_checks_entire_duration_not_only_start(self):
        intervals = [{'start_ms': 100, 'end_ms': 200, 'units': 2}]
        self.assertEqual(200, exp.earliest(0, 150, 1, intervals, 2))
        self.assertEqual(0, exp.earliest(0, 50, 1, intervals, 2))

    def test_empty_many_slot_K_is_null_without_dropping_E(self):
        a = {'required_task_ids': ['a', 'b'], 'completed_task_ids': [], 'tasks': {'a': {}, 'b': {}}}
        value = exp.all_slot_common([a, deepcopy(a), deepcopy(a)])
        self.assertEqual(2, value['required_count'])
        self.assertEqual(0, value['common_count'])
        self.assertEqual(0, value['coverage'])
        self.assertFalse(value['eligible'])
        self.assertTrue(all(m['slot_means'] == [None, None, None] for m in value['metrics'].values()))

    def test_many_slot_K_intersection_uses_all_slots(self):
        def row(ids):
            return {'required_task_ids': ['a', 'b'], 'completed_task_ids': ids,
                    'tasks': {t: {m: 10 for m in exp.old.TIME_NAMES} for t in ('a', 'b')}}
        v = exp.all_slot_common([row(['a', 'b']), row(['a']), row(['a', 'b']), row(['a', 'b']), row(['a', 'b']), row(['a', 'b'])])
        self.assertEqual(['a'], v['common_task_ids'])
        self.assertEqual(.5, v['coverage'])
        self.assertTrue(all(m['slot_means'] == [10]*6 for m in v['metrics'].values()))


class SavedLatencyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = exp.read(exp.PLAN)
        cls.docs = [exp.read(exp.config_path(i)) for i in range(44)]
        cls.stat = exp.read(exp.OUT + '/statistics.json')

    def test_lock_and_old_materials_unchanged(self):
        lock = exp.verify_lock()
        self.assertGreater(len(lock['protected_sha256']), 835)
        self.assertEqual(self.plan, exp.build_plan())
        self.assertIsNone(lock['independent_design_acceptance'])
        self.assertIsNone(lock['implementation_acceptance'])

    def test_four_new_baselines_reproduce_all_old_fields(self):
        gate = exp.read(exp.GATE)
        self.assertEqual(4, len(gate['slots']))
        for s in gate['slots']:
            d = self.docs[s['index']]
            self.assertEqual(s['run'], d['runs'][0])
            ref = exp.read(d['world']['old_early_reference_path'])['runs'][0]
            self.assertEqual(exp.legacy_projection(s['run']), exp.legacy_projection(ref))

    def test_all_saved_event_audits_and_statistics_recount(self):
        for d in self.docs:
            self.assertEqual(d['pair'], exp.old.pair_audit(d['input'], d['runs']))
        self.assertEqual(self.stat, exp.build_statistics())

    def test_prediction_check_reports_outcome_not_postfit(self):
        matches = 0
        for d in self.docs:
            self.assertEqual(d['config']['prediction'], next(c for c in self.plan['configurations'] if c['config_id'] == d['config']['config_id'])['prediction'])
            pred = d['config']['prediction']
            ok = all(all(a['tasks']['water'][k] == pred['water'][arm][k] for k in ('start_ms', 'completion_ms'))
                     for arm, a in zip(exp.old.ARMS, d['pair']['audits']))
            ok = ok and sorted(d['pair']['running_task_ids']) == pred['expected_running_task_ids']
            ok = ok and sorted(d['pair']['unstarted_task_ids']) == pred['expected_unstarted_task_ids']
            self.assertEqual(ok, d['prediction_matches'])
            matches += ok
        self.assertEqual(matches, self.stat['prediction_matches'])

    def test_no_future_private_identity_or_unequal_calls(self):
        for d in self.docs:
            self.assertEqual(d['runs'][0]['calls'], d['runs'][1]['calls'])
            self.assertTrue(d['pair']['full_prefix_through_commit_equal'])
            for call in d['runs'][0]['calls']:
                request = call['request']
                self.assertEqual('F2-public-home', request['episode_id'])
                self.assertNotIn('LW1-', __import__('json').dumps(request))
                self.assertEqual({t['task_id'] for t in d['input']['task_stream'] if t['release_at_ms'] <= request['current_time_ms']},
                                 {t['task_id'] for t in request['state']['coordination_context']['requests']})

    def test_physical_services_never_cancelled_and_capacity_enforced(self):
        for d in self.docs:
            self.assertTrue(d['pair']['running_service_intervals_unchanged'])
            for a in d['pair']['audits']:
                self.assertEqual(0, a['metrics']['executed_capacity_violation_duration_ms'])
                self.assertEqual(4, a['denominators']['required'])

    def test_24_information_diagnostics_isolated(self):
        rows = [r for n in (1, 3, 5, 7) for r in exp.read(exp.OUT+'/diagnostic_world_'+str(n).zfill(2)+'.json')['records']]
        self.assertEqual(24, len(rows))
        self.assertTrue(all(r['prefix_equal'] for r in rows))

    def test_changed_duration_fails_main_audit(self):
        d = self.docs[0]
        run = deepcopy(d['runs'][0])
        x = next(x for x in run['trace']['events'] if x['type'] == 'reservation_review_committed')
        x['timestamp_ms'] += 1
        with self.assertRaises(ValueError):
            exp.old.audit(d['input'], run)

    def test_forged_completion_fails_both_recounts(self):
        d = self.docs[0]
        run = deepcopy(d['runs'][0])
        x = next(x for x in run['trace']['events'] if x['type'] == 'action_completed')
        x['reservation_generation'] += 1
        with self.assertRaises(ValueError):
            exp.old.audit(d['input'], run)
        with self.assertRaises(ValueError):
            cross.recount(d['input'], run)

    def test_separate_arithmetic_does_not_run_simulator(self):
        outcome = cross.build()
        self.assertEqual(0, outcome['new_simulator_runs'])
        self.assertEqual(88, outcome['formal_runs'])
        self.assertGreater(outcome['top_level_checks'], 1000)

    def test_no_deployment_or_novelty_claim(self):
        self.assertFalse(self.stat['novelty_proved'])
        self.assertFalse(self.stat['deployment_latency_measured'])
        self.assertFalse(self.stat['rankings'])
        self.assertIsNone(self.stat['independent_acceptance'])


if __name__ == '__main__':
    unittest.main()
