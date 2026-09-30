import itertools
import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_multimode_replication_20260930 import build, records_for
from probe_c3_multimode_20260930 import public_plan, run_one
from evaluate import task_accepts_action
from runtime.episode_validation import validate_event_episode

class DualModeReplicationTests(unittest.TestCase):
    def records(self, episode, laundry='eco', meal='eco'):
        return records_for(episode, {'laundry': laundry, 'meal': meal}, {'laundry': 800, 'meal': 1000, 'water': 1200})

    def test_two_service_sets_and_negative_off(self):
        for capacity in (3, 4, 6):
            episode = build(capacity)
            self.assertFalse(validate_event_episode(episode))
            for task in episode['task_stream']:
                target = task['action_template']['target']
                self.assertFalse(task_accepts_action({'target': target, 'operation': 'off'}, task))
                if task['task_id'] != 'water':
                    for operation in ('eco', 'fast'):
                        self.assertTrue(task_accepts_action({'target': target, 'operation': operation}, task))

    def test_fixed_modes_preserved_and_deadlines_feasible_for_all_combinations(self):
        for capacity in (3, 4, 6):
            episode = build(capacity)
            for laundry, meal in itertools.product(('eco', 'fast'), repeat=2):
                row = run_one(episode, self.records(episode, laundry, meal), 'FixedProposalExact')
                self.assertEqual({'laundry': laundry, 'meal': meal, 'water': 'prepare'}, row['chosen_modes'])
                self.assertTrue(row['all_deadlines_met'])
                self.assertEqual(0, row['process_violation_ms'])

    def test_no_competition_optimum_and_original_response_latencies(self):
        episode = build(6)
        row = run_one(episode, self.records(episode), 'ReleasedModeEnumerationExact')
        self.assertEqual('fast', row['chosen_modes']['laundry'])
        self.assertEqual('fast', row['chosen_modes']['meal'])
        self.assertEqual(241300, row['last_actual_completion_ms'])
        self.assertEqual({'laundry': 800, 'meal': 1000, 'water': 1200}, row['model_latency_by_task_ms'])
        self.assertTrue(all(t == 1300 for t in row['task_start_wait_ms'].values()))

    def test_public_plan_independent_of_hidden_costs_and_scoring(self):
        episode = build(3)
        records = self.records(episode)
        expected = public_plan(episode, records, True)
        poisoned = deepcopy(episode)
        for task in poisoned['task_stream']:
            task['action_template'].update(duration_ms=1, power_kw=999, operation='off')
            task.pop('acceptable_actions')
        self.assertEqual(expected, public_plan(poisoned, records, True))

if __name__ == '__main__':
    unittest.main()
