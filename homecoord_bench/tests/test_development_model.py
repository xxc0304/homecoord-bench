import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_development_model_20260930 import locked, late_run, BoundedClient, score, LATE_LABELS
from build_task_family_split_20260930 import records_for, FamilyScriptClient

class DevelopmentModelTests(unittest.TestCase):
    def episode(self):
        _, episodes = locked()
        return next(e for e in episodes if e['family_block'] == 'F2' and e['pairing']['resource_arm'] == 'competition')

    def early(self, episode):
        modes = {t['task_id']: t['action_template']['operation'] for t in episode['task_stream']}
        all_records = records_for(episode, modes, {t['task_id']: 800 for t in episode['task_stream']})
        return {t['task_id']: all_records[t['task_id']] for t in episode['task_stream'] if t['release_at_ms'] == 0}

    def test_fresh_late_request_uses_runtime_release_state_for_each_policy(self):
        episode = self.episode()
        for policy in LATE_LABELS:
            provider = FamilyScriptClient({'water': 'prepare'}, {'water': 800})
            row = late_run(episode, self.early(episode), policy, provider)
            self.assertTrue(row['all_tasks_served'])
            self.assertEqual(1, len(row['late_records']))
            request = row['late_records']['water']['request']
            self.assertEqual(60000, request['current_time_ms'])
            self.assertGreater(request['state_version'], episode['initial_state']['version'])
            self.assertEqual({'laundry', 'dishes', 'cleaning', 'water'},
                             {r['task_id'] for r in request['state']['coordination_context']['requests']})
            self.assertTrue(row['late_request_audits'][0]['request_matches_runtime'])
            self.assertEqual(row['late_records']['water']['logical_latency_ms'], row['model_latency_by_task_ms']['water'])

    def test_late_api_failure_is_preserved_and_missing_service_is_not_zero_wait(self):
        class FailedProvider:
            def decide(self, *_args):
                raise RuntimeError('test network failure')
        episode = self.episode()
        row = late_run(episode, self.early(episode), 'GateRetryRule', FailedProvider())
        self.assertIn('water', row['late_errors'])
        self.assertFalse(row['all_tasks_served'])
        self.assertIsNone(row['task_start_wait_ms']['water'])
        self.assertIsNone(row['task_completion_latency_ms']['water'])
        self.assertEqual({}, row['late_records'])
        self.assertFalse(row['scores'][0]['semantic_correct'])

    def test_budget_limit_rejects_before_provider_call(self):
        class Fake:
            api_key = 'dummy'
            calls = 0
            def decide(self, *_args):
                self.calls += 1
                return {}
        provider = Fake()
        bounded = BoundedClient(provider, already_attempted=25, limit=26)
        bounded.decide({})
        with self.assertRaisesRegex(RuntimeError, 'limit reached'):
            bounded.decide({})
        self.assertEqual(1, provider.calls)

    def test_off_is_authorized_but_not_correct_service(self):
        episode = self.episode()
        record = deepcopy(self.early(episode)['laundry'])
        record['decision']['actions'][0]['operation'] = 'off'
        result = score(episode, 'laundry', record)
        self.assertTrue(result['authorized'])
        self.assertFalse(result['semantic_correct'])

    def test_locked_pilot_only_contains_dev_and_public_ids_do_not_encode_arm(self):
        design, episodes = locked()
        self.assertEqual(26, design['max_api_requests'])
        self.assertEqual(6, len(episodes))
        for e in episodes:
            self.assertEqual('development', e['split'])
            self.assertNotIn('competition', e['episode_id'])
            self.assertNotIn('late', e['episode_id'])

if __name__ == '__main__':
    unittest.main()
