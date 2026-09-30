import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.task_response_metrics import task_response_metrics
from runtime.information_contract import released_scheduler_view, trace_information_audit


class TaskResponseContractTests(unittest.TestCase):
    def episode(self):
        return {'home': {'resources': {'max_power_kw': 3}}, 'task_stream': [
            {'task_id': 't', 'agent_id': 'a', 'release_at_ms': 60000,
             'completion_deadline_ms': 64000, 'priority': 1, 'goal': 'warm',
             'required_action': {'target': 'water', 'operation': 'warm'},
             'action_template': {'hidden': True}}]}

    def event(self, kind, at, operation='warm'):
        return {'type': kind, 'timestamp_ms': at, 'task_id': 't', 'proposal_id': 'p',
                'target': 'water', 'operation': operation, 'duration_ms': 2000, 'power_kw': 2}

    def test_own_release_and_actual_completion(self):
        result = task_response_metrics(self.episode(), [self.event('action_started', 62000), self.event('action_completed', 65000)])
        self.assertEqual({'t': 2000}, result['task_start_wait_ms'])
        self.assertEqual({'t': 5000}, result['task_completion_latency_ms'])
        self.assertEqual({'t': 1000}, result['task_completion_tardiness_ms'])

    def test_wrong_action_and_missing_are_not_zero_wait(self):
        for events in ([], [self.event('action_started', 61000, 'off'), self.event('action_completed', 63000, 'off')]):
            result = task_response_metrics(self.episode(), events)
            self.assertIsNone(result['task_start_wait_ms']['t'])
            self.assertFalse(result['task_start_within_1s']['t'])
            self.assertEqual(1, result['task_unstarted_count'])

    def test_start_does_not_imply_completion(self):
        result = task_response_metrics(self.episode(), [self.event('action_started', 61000)])
        self.assertTrue(result['task_start_within_1s']['t'])
        self.assertEqual(1, result['task_incomplete_count'])
        self.assertIsNone(result['task_completion_latency_ms']['t'])

    def test_early_start_rejected(self):
        with self.assertRaises(ValueError):
            task_response_metrics(self.episode(), [self.event('action_started', 59999)])

    def test_information_boundaries(self):
        costs = {'t': {'duration_ms': 2000, 'power_kw': 2}}
        for now, released, returned in ((59999, {'t'}, set()), (60000, set(), {'t'})):
            with self.assertRaises(ValueError):
                released_scheduler_view(self.episode(), now, released, returned, costs)
        view = released_scheduler_view(self.episode(), 60000, {'t'}, set(), costs)
        self.assertNotIn('action_template', view['released_tasks'][0])
        self.assertNotIn('required_action', view['released_tasks'][0])
        self.assertFalse(view['released_tasks'][0]['proposal_has_returned'])

    def test_reservation_running_and_removal(self):
        reserved = {**self.event('action_reserved', 61000), 'scheduled_start_ms': 62000}
        events = [self.event('task_released', 60000), self.event('proposal_returned', 60900),
                  reserved, self.event('action_started', 62000), self.event('action_completed', 65000)]
        views = trace_information_audit(self.episode(), events, {'t': {'duration_ms': 2000, 'power_kw': 2}})
        self.assertEqual('reserved', views[2]['committed_actions'][0]['status'])
        self.assertEqual(62000, views[2]['committed_actions'][0]['scheduled_start_ms'])
        self.assertEqual('running', views[3]['committed_actions'][0]['status'])
        self.assertEqual([], views[4]['committed_actions'])
        rejected = trace_information_audit(self.episode(), events[:3] + [self.event('action_rejected', 62000)], {'t': {'duration_ms': 2000, 'power_kw': 2}})
        self.assertEqual([], rejected[-1]['committed_actions'])

if __name__ == '__main__':
    unittest.main()
