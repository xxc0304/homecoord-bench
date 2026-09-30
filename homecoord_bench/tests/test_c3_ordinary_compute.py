import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_ordinary_compute_20260930 import execute, scripted, audit_jobs
from runtime.event_simulator import run_event_simulation

class OrdinaryComputeTests(unittest.TestCase):
    def test_profiling_preserves_results_and_exercises_retry(self):
        episode, records = scripted()
        for policy in ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator'):
            reference = execute(episode, records, policy)
            measured = execute(episode, records, policy, measure=True)
            for field in ('all_tasks_served', 'all_deadlines_met', 'task_start_wait_ms', 'task_completion_latency_ms',
                          'last_actual_completion_ms', 'model_latency_by_task_ms'):
                self.assertEqual(reference[field], measured[field])
            self.assertEqual(3, sum(m['stage'] == 'dispatch' for m in measured['measurements']))
            if policy == 'GateRetryRule':
                self.assertGreater(measured['retry_scheduled_count'], 0)
                self.assertGreater(sum(m['stage'] == 'retry_batch' for m in measured['measurements']), 0)

    def test_one_worker_serializes_simultaneous_dispatches(self):
        episode, records = scripted()
        row = execute(episode, records, 'ConstraintCoordinator', profile={'dispatch_ms': 5, 'retry_batch_ms': 0})
        starts = [e for e in row['events'] if e['type'] == 'ordinary_coordination_started']
        finishes = [e for e in row['events'] if e['type'] == 'ordinary_coordination_completed']
        self.assertEqual([800, 805, 810], [e['timestamp_ms'] for e in starts])
        self.assertEqual([805, 810, 815], [e['timestamp_ms'] for e in finishes])
        self.assertEqual(15, audit_jobs(row)['charged_worker_service_ms'])
        self.assertEqual(15, audit_jobs(row)['worker_queue_wait_ms'])
        self.assertEqual({'laundry': 800, 'water': 800, 'meal': 800}, row['model_latency_by_task_ms'])

    def test_retry_is_charged_separately_and_only_after_resource_release(self):
        episode, records = scripted()
        row = execute(episode, records, 'GateRetryRule', profile={'dispatch_ms': 2, 'retry_batch_ms': 7})
        self.assertTrue(row['all_tasks_served'])
        self.assertGreater(audit_jobs(row)['retry_batch_jobs'], 0)
        retries = [e for e in row['events'] if e['type'] == 'ordinary_coordination_started' and e['stage'] == 'retry_batch']
        released = {e['timestamp_ms'] for e in row['events'] if e['type'] == 'action_completed'}
        self.assertTrue(all(e['timestamp_ms'] in released for e in retries))
        self.assertTrue(all(e['duration_ms'] == 7 for e in retries))

    def test_zero_profile_is_identity_and_never_charges_unused_retry(self):
        episode, records = scripted()
        for policy in ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator'):
            zero = execute(episode, records, policy)
            profiled = execute(episode, records, policy, profile={'dispatch_ms': 0, 'retry_batch_ms': 0})
            self.assertEqual(zero['task_start_wait_ms'], profiled['task_start_wait_ms'])
            self.assertEqual(zero['task_completion_latency_ms'], profiled['task_completion_latency_ms'])
            if policy != 'GateRetryRule':
                self.assertEqual(0, audit_jobs(profiled)['retry_batch_jobs'])

    def test_updates_continue_and_only_invalid_preconditions_reject(self):
        for patch, served in (({'diagnostics.tick': 1}, True), ({'devices.water_heater': 'busy'}, False)):
            episode, records = scripted()
            row = execute(episode, records, 'GateRetryRule', profile={'dispatch_ms': 5, 'retry_batch_ms': 5},
                          update={'event': 'during_compute', 'at_ms': 805, 'patch': patch})
            audit_jobs(row)
            self.assertEqual(served, row['task_service']['water'])
            self.assertTrue(any(e.get('state_changed_during_compute') for e in row['events']
                                if e['type'] == 'ordinary_coordination_completed'))
            if not served:
                self.assertIsNone(row['task_start_wait_ms']['water'])
                self.assertIsNone(row['task_completion_latency_ms']['water'])

    def test_conflicting_or_malformed_delay_contract_rejected(self):
        episode, _ = scripted()
        for profile in ({'dispatch_ms': 1}, {'dispatch_ms': -1, 'retry_batch_ms': 0},
                        {'dispatch_ms': True, 'retry_batch_ms': 0}, {'dispatch_ms': 1.5, 'retry_batch_ms': 0}):
            episode['simulation']['coordination_compute_profile'] = profile
            with self.assertRaisesRegex(ValueError, 'compute profile must contain'):
                run_event_simulation(episode, None, 'ConstraintCoordinator', '')
        episode['simulation']['coordination_compute_profile'] = {'dispatch_ms': 1, 'retry_batch_ms': 1}
        with self.assertRaisesRegex(ValueError, 'without other compute'):
            run_event_simulation(episode, None, 'ConstraintCoordinator', '', coordination_delay_ms=1)

if __name__ == '__main__':
    unittest.main()
