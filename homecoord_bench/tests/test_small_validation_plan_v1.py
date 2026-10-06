import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from homecoord_bench.task_revision import small_validation_plan_v1 as p
from homecoord_bench.task_revision.f2_information import build_agent_request


class SmallValidationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = p.build()
        cls.sources = {e['episode_id']: e for e in p.read(p.SOURCE)['episodes']}

    def test_saved_plan_reproducible(self):
        self.assertEqual(self.plan, p.read(p.OUT))

    def test_counts_unique_slots_and_complete_pairs(self):
        d = self.plan
        self.assertEqual((28, 84, 72), (len(d['configurations']), len(d['run_slots']), len(d['pairs'])))
        self.assertEqual(84, len({x['slot_id'] for x in d['run_slots']}))
        ids = {x['slot_id'] for x in d['run_slots']}
        self.assertTrue(all(x['left'] in ids and x['right'] in ids for x in d['pairs']))
        self.assertTrue(all(len(x['required_requests']) == 4 for x in d['configurations']))

    def test_one_factor_and_clock_rules(self):
        for c in self.plan['configurations']:
            source = self.sources[c['source_episode_id']]
            e = p.variant(source, c['factor'], c['value_ms'])
            self.assertEqual(c['changed_paths_excluding_private_identity'], p.differences(source, e))
            w = next(t for t in e['task_stream'] if t['task_id'] == 'water')
            old = next(t for t in source['task_stream'] if t['task_id'] == 'water')
            if c['factor'] == 'water_release_offset_ms':
                self.assertEqual(old['completion_deadline_ms']-old['release_at_ms'], w['completion_deadline_ms']-w['release_at_ms'])
                self.assertEqual(w['release_at_ms'], e['exogenous_events'][0]['at_ms'])
            if c['factor'] == 'command_latency_ms':
                self.assertEqual(source['task_stream'], e['task_stream'])
            self.assertEqual(source['action_grounding'], e['action_grounding'])
            self.assertEqual(source['public_devices'], e['public_devices'])

    def test_all_28_constructive_witnesses(self):
        for c in self.plan['configurations']:
            e = p.variant(self.sources[c['source_episode_id']], c['factor'], c['value_ms'])
            p.verify_witness(e, c['feasibility_certificate']['intervals'])
            self.assertEqual('offline_all_requests_not_online_input_or_baseline', c['feasibility_certificate']['information'])

    def test_invalid_witness_not_accepted(self):
        c = self.plan['configurations'][0]
        e = p.variant(self.sources[c['source_episode_id']], c['factor'], c['value_ms'])
        for kind in ('duplicate', 'time', 'units', 'deadline'):
            xs = deepcopy(c['feasibility_certificate']['intervals'])
            if kind == 'duplicate': xs.append(xs[0])
            elif kind == 'time': xs[0]['end_ms'] += 1
            elif kind == 'units': xs[0]['units'] += 1
            else:
                xs[0]['start_ms'] += 9999999; xs[0]['end_ms'] += 9999999
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                p.verify_witness(e, xs)

    def test_public_input_no_water_before_release_for_all_configs(self):
        for c in self.plan['configurations']:
            e = p.variant(self.sources[c['source_episode_id']], c['factor'], c['value_ms'])
            t = e['task_stream'][0]; agent = next(a for a in e['agents'] if a['agent_id'] == t['agent_id'])
            request = build_agent_request(e, agent, t, architecture='DeadlineAwareCoordinator', current_time_ms=0)
            self.assertEqual(3, len(request['state']['coordination_context']['requests']))
            self.assertNotIn('water', [x['task_id'] for x in request['state']['coordination_context']['requests']])
            self.assertEqual('F2-public-home', request['episode_id'])
            self.assertNotIn('SV1', json.dumps(request))

    def test_adequate_controls_and_fixed_grid(self):
        self.assertEqual(14, sum(c['capacity_units'] == 6 for c in self.plan['configurations']))
        for eid in {c['source_episode_id'] for c in self.plan['configurations']}:
            cs = [c for c in self.plan['configurations'] if c['source_episode_id'] == eid]
            self.assertEqual(7, len(cs))
            self.assertEqual({('baseline',0),('water_budget_offset_ms',-30000),('water_budget_offset_ms',30000),
                              ('water_release_offset_ms',-30000),('water_release_offset_ms',30000),
                              ('command_latency_ms',0),('command_latency_ms',500)},
                             {(c['factor'],c['value_ms']) for c in cs})

    def test_plan_not_execution_or_freeze(self):
        self.assertFalse(self.plan['scores_computed'])
        self.assertEqual(0, self.plan['simulator_runs'])
        self.assertEqual(0, self.plan['api_calls'])
        self.assertFalse(self.plan['feasibility_is_online_guarantee'])
        self.assertFalse(self.plan['historical_runs_reused_as_new_baselines'])
        self.assertFalse(self.plan['factorial_interactions_planned'])
        self.assertEqual('draft_static_plan_not_frozen_or_executed', self.plan['status'])

    def test_hash_error_or_unknown_factor_blocks(self):
        with patch.object(p, 'sha', return_value='bad'), self.assertRaises(AssertionError): p.build()
        with self.assertRaises(ValueError): p.variant(next(iter(self.sources.values())), 'unknown', 1)


if __name__ == '__main__':
    unittest.main()

