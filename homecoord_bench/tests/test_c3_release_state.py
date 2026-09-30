import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_release_state_20260930 import ReleaseStateClient, audit_release_request, SOURCE
from probe_c3_scale_release_20260930 import load
from probe_c3_information_baselines_20260930 import adapt
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from runtime.event_simulator import run_event_simulation

class FakeLateProvider:
    def __init__(self, records):
        self.records = records
        self.requests = []
    def decide(self, request, instructions):
        self.requests.append(deepcopy(request))
        return deepcopy(self.records[request['task']['task_id']]['decision'])

class ReleaseStateTests(unittest.TestCase):
    def test_only_late_request_is_fresh_and_state_matches_prefix(self):
        _, episodes = load()
        source = json.loads(SOURCE.read_text(encoding='utf8'))
        for batch in source['batches'][::3]:
            episode = episodes[batch['template'], 'tight', 'urgent_late', 1.6]
            for label in ('GateRetryRule', 'ReleasedFeasibilityFallback'):
                changed, policy = adapt(episode, label) if label.startswith('Released') else (deepcopy(episode), label)
                provider = FakeLateProvider(batch['sample']['records'])
                client = ReleaseStateClient(batch['sample']['records'], provider, 'test')
                trace, _ = run_event_simulation(changed, client, policy, PILOT_INSTRUCTIONS, shared_safety_gate=True)
                self.assertEqual(1, len(provider.requests))
                self.assertEqual(len(episode['task_stream']) - 1, len(client.reused))
                request = client.fresh[0]['request']
                self.assertEqual(60000, request['current_time_ms'])
                self.assertNotIn('required_action', request['task'])
                audited = audit_release_request(changed, trace, request)
                self.assertTrue(audited['reconstructed_at_release'])
                self.assertFalse(audited['visible_state_differs_from_initial'])
                poisoned = deepcopy(request)
                poisoned['state_version'] += 1
                with self.assertRaises(ValueError):
                    audit_release_request(changed, trace, poisoned)

    def test_non_release_request_rejected(self):
        client = ReleaseStateClient({}, FakeLateProvider({}), 'test')
        with self.assertRaises(ValueError):
            client.decide({'task': {'task_id': 'x'}, 'current_time_ms': 999}, '')

if __name__ == '__main__':
    unittest.main()
