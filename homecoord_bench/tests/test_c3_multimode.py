import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_multimode_20260930 import build, records_for, run_one, public_plan
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient
from runtime.protocol import build_agent_request
from runtime.episode_validation import validate_event_episode
from evaluate import task_accepts_action

class MultiModeTests(unittest.TestCase):
    def records(self, episode, mode='eco'):
        return records_for(episode, mode, {'laundry': 800, 'water': 1000, 'meal': 1200})

    def test_eco_and_fast_score_correct_with_actual_different_completion(self):
        episode = build(5)
        results = [run_one(episode, self.records(episode, mode), 'ConstraintCoordinator') for mode in ('eco', 'fast')]
        self.assertTrue(all(r['all_tasks_served'] for r in results))
        self.assertNotEqual(results[0]['task_completion_latency_ms']['laundry'], results[1]['task_completion_latency_ms']['laundry'])
        task = episode['task_stream'][0]
        self.assertTrue(task_accepts_action({'target': 'washer', 'operation': 'eco'}, task))
        self.assertTrue(task_accepts_action({'target': 'washer', 'operation': 'fast'}, task))
        self.assertFalse(task_accepts_action({'target': 'washer', 'operation': 'off'}, task))

    def test_off_is_authorized_but_not_service_or_zero_wait(self):
        episode = build(5)
        records = self.records(episode)
        records['laundry']['decision']['actions'][0]['operation'] = 'off'
        row = run_one(episode, records, 'ConstraintCoordinator')
        self.assertFalse(row['all_tasks_served'])
        self.assertIsNone(row['task_start_wait_ms']['laundry'])
        self.assertIsNone(row['task_completion_latency_ms']['laundry'])

    def test_scoring_set_and_template_hidden_from_provider(self):
        episode = build(3)
        task = episode['task_stream'][0]
        request = build_agent_request(episode, episode['agents'][0], task, architecture='IndependentMultiAgent', current_time_ms=0)
        self.assertNotIn('acceptable_actions', request['task'])
        self.assertNotIn('action_template', request['task'])
        self.assertIn('coordination_context', request['state'])

    def test_public_plan_ignores_hidden_template_and_scoring_choice(self):
        episode = build(3)
        records = self.records(episode)
        expected = public_plan(episode, records, True)
        poisoned = deepcopy(episode)
        for task in poisoned['task_stream']:
            task['action_template'].update({'duration_ms': 1, 'power_kw': 999, 'operation': 'off'})
            task.pop('acceptable_actions')
        self.assertEqual(expected, public_plan(poisoned, records, True))

    def test_best_mode_depends_on_capacity_and_has_all_returned_clock(self):
        for cap, best_mode, duration in ((3, 'fast', 540000), (4, 'eco', 480000), (5, 'fast', 300000)):
            episode = build(cap)
            row = run_one(episode, self.records(episode), 'ReleasedModeEnumerationExact')
            self.assertEqual(best_mode, row['chosen_laundry_mode'])
            self.assertEqual(1300 + duration, row['last_actual_completion_ms'])
            self.assertTrue(row['all_deadlines_met'])
            self.assertTrue(all(v >= 1300 for v in row['task_start_wait_ms'].values()))

    def test_fixed_proposal_exact_does_not_change_mode(self):
        for mode in ('eco', 'fast'):
            episode = build(3)
            row = run_one(episode, self.records(episode, mode), 'FixedProposalExact')
            self.assertEqual(mode, row['chosen_laundry_mode'])
            self.assertTrue(row['all_deadlines_met'])

    def test_rejects_missing_operation_and_ambiguous_service_contract(self):
        episode = build(3)
        episode['task_stream'][0]['acceptable_actions'] = [{'target': 'washer'}]
        self.assertTrue(validate_event_episode(episode))
        with self.assertRaises(ValueError):
            task_accepts_action({'target': 'washer', 'operation': 'off'}, episode['task_stream'][0])
        episode = build(3)
        episode['task_stream'][0]['required_action'] = {'target': 'washer', 'operation': 'eco'}
        self.assertTrue(validate_event_episode(episode))

    def test_exact_baseline_rejects_future_tasks(self):
        episode = build(3)
        records = self.records(episode)
        episode['task_stream'][1]['release_at_ms'] = 60000
        with self.assertRaisesRegex(ValueError, 'all-released'):
            public_plan(episode, records, True)

if __name__ == '__main__':
    unittest.main()
