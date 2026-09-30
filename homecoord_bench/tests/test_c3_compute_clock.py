import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_multimode_replication_20260930 import build, records_for
from probe_c3_multimode_20260930 import public_plan
from probe_c3_compute_clock_20260930 import execute
from runtime.event_simulator import run_event_simulation

class ComputeClockTests(unittest.TestCase):
    def setup_case(self):
        episode = build(6)
        records = records_for(episode, {'laundry': 'fast', 'meal': 'fast'},
                              {'laundry': 800, 'water': 1200, 'meal': 1000})
        return episode, records, public_plan(episode, records, False)

    def test_shared_compute_once_and_command_delay_not_double_counted(self):
        episode, records, plan = self.setup_case()
        zero = execute(episode, records, plan, 'FixedProposalExact', 0)
        timed = execute(episode, records, plan, 'FixedProposalExact', 250)
        self.assertTrue(timed['all_deadlines_met'])
        self.assertEqual(250, timed['last_actual_completion_ms'] - zero['last_actual_completion_ms'])
        self.assertEqual({'laundry': 1550, 'meal': 1550, 'water': 1550}, timed['task_start_wait_ms'])
        self.assertEqual(zero['model_latency_by_task_ms'], timed['model_latency_by_task_ms'])
        self.assertEqual(1, sum(e['type'] == 'coordination_completed' for e in timed['clock_events']))

    def test_state_invalidation_during_computation_and_command(self):
        for timestamp in (1300, 1500, 1550):
            episode, records, plan = self.setup_case()
            row = execute(episode, records, plan, 'FixedProposalExact', 250,
                          {'event': 'test_invalid', 'at_ms': timestamp, 'patch': {'devices.water_heater': 'busy'}})
            self.assertFalse(row['task_service']['water'])
            self.assertIsNone(row['task_start_wait_ms']['water'])
            self.assertIsNone(row['task_completion_latency_ms']['water'])
            self.assertTrue(any(e['type'] == 'action_rejected' and e['task_id'] == 'water' for e in row['clock_events']))

    def test_same_clock_state_update_precedes_compute_completion(self):
        episode, records, plan = self.setup_case()
        row = execute(episode, records, plan, 'FixedProposalExact', 250,
                      {'event': 'test_invalid', 'at_ms': 1450, 'patch': {'devices.water_heater': 'busy'}})
        completed = next(e for e in row['clock_events'] if e['type'] == 'coordination_completed')
        self.assertTrue(completed['state_changed_during_compute'])
        self.assertFalse(row['task_service']['water'])

    def test_benign_version_change_keeps_valid_actions(self):
        episode, records, plan = self.setup_case()
        row = execute(episode, records, plan, 'FixedProposalExact', 250,
                      {'event': 'unrelated', 'at_ms': 1300, 'patch': {'diagnostics.tick': 1}})
        self.assertTrue(row['all_tasks_served'])
        self.assertTrue(next(e for e in row['clock_events'] if e['type'] == 'coordination_completed')['state_changed_during_compute'])

    def test_compute_can_cross_deadline_without_forcing_success(self):
        episode, records, _ = self.setup_case()
        task = next(t for t in episode['task_stream'] if t['task_id'] == 'water')
        task['completion_deadline_ms'] = 241400
        for request in episode['initial_state']['values']['coordination_context']['requests']:
            if request['task_id'] == 'water':
                request['deadline_ms'] = 241400
        plan = public_plan(episode, records, False)
        self.assertTrue(execute(episode, records, plan, 'FixedProposalExact', 0)['all_deadlines_met'])
        delayed = execute(episode, records, plan, 'FixedProposalExact', 250)
        self.assertTrue(delayed['all_tasks_served'])
        self.assertFalse(delayed['all_deadlines_met'])

    def test_reject_bad_delay_and_unsupported_plan_policy(self):
        episode, _, plan = self.setup_case()
        for delay in (-1, True, 1.5):
            episode['simulation'].update(released_batch_plan=plan, released_batch_compute_ms=delay)
            with self.assertRaisesRegex(ValueError, 'non-negative integer'):
                run_event_simulation(episode, None, 'FixedHoldCoordinator', '')
        episode['simulation']['released_batch_compute_ms'] = 100
        with self.assertRaisesRegex(ValueError, 'FixedHold released plan'):
            run_event_simulation(episode, None, 'DeadlineAwareCoordinator', '')

if __name__ == '__main__':
    unittest.main()
