import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.protection_revision_v6 import episode, run, bundle, serialize, POLICIES, NoAction, Slow, audit
from homecoord_bench.task_revision.protection_revision import bundle as frozen_bundle, serialize as frozen_serialize
from homecoord_bench.task_revision.milestone import FixedProposals, drafts
from homecoord_bench.task_revision.event_simulator_v6 import run_event_simulation as v6
from homecoord_bench.task_revision.event_simulator_v5 import run_event_simulation as v5

ROOT = Path(__file__).resolve().parents[2]


class ProtectionV6Tests(unittest.TestCase):
    def test_full_first_input_identical_across_four_future_conditions(self):
        for kind in ('LIGHT', 'BLINDS'):
            for policy in POLICIES:
                requests = [run(episode(kind, c, b), policy)['trace']['agent_requests'][0]
                            for c in ('CONFLICT', 'SAFE') for b in ('legality', 'equal_response')]
                self.assertTrue(all(x == requests[0] for x in requests))

    def test_private_ids_and_future_events_cannot_change_visible_input(self):
        for kind in ('LIGHT', 'BLINDS'):
            a = episode(kind, 'SAFE')
            b = deepcopy(a)
            b['episode_id'] = 'SECRET-CONFLICT-equal_response'
            b['base_episode_id'] = 'SECRET-SAFE-legality'
            b['variant']['condition'] = 'SECRET'
            b['exogenous_events'][0]['at_ms'] = 6100
            b['task_stream'][1]['release_at_ms'] = 6600
            for policy in POLICIES:
                self.assertEqual(run(a, policy)['trace']['agent_requests'][0],
                                 run(b, policy)['trace']['agent_requests'][0])

    def test_actual_provider_and_saved_trace_are_same_public_requests(self):
        class Capture(FixedProposals):
            def __init__(self): self.seen = []
            def decide(self, request, instructions):
                self.seen.append(deepcopy(request))
                return super().decide(request, instructions)
        provider = Capture()
        r = run(episode('LIGHT', 'SAFE'), provider=provider)
        self.assertEqual(provider.seen, r['trace']['agent_requests'])
        for request in provider.seen:
            text = json.dumps(request)
            for label in ('CONFLICT', 'SAFE', 'equal_response', 'legality', 'C1R3'):
                self.assertNotIn(label, text)
            self.assertEqual('HC-M02', request['episode_id'])

    def test_episode_preparation_side_channel_is_rejected(self):
        class Hook(FixedProposals):
            def prepare_release_batch(self, *args): raise AssertionError('must never run')
        with self.assertRaises(ValueError): run(episode('LIGHT', 'SAFE'), provider=Hook())

    def test_admitted_no_action_is_correct_admission_not_service(self):
        for kind in ('LIGHT', 'BLINDS'):
            for policy in POLICIES:
                e = episode(kind, 'SAFE'); tid = e['task_stream'][1]['task_id']
                r = run(e, policy, NoAction())
                self.assertTrue(r['audit']['admission_correct'][tid])
                self.assertEqual('admitted', r['audit']['observed_admission'][tid])
                self.assertEqual('unresolved', r['audit']['request_status'][tid])
                self.assertFalse(r['result']['task_correct_action_completed'][tid])
                self.assertIsNone(r['result']['task_completion_latency_ms'][tid])
                self.assertNotIn('correct_disposition', r['audit'])

    def test_precondition_failure_and_late_completion_are_separate(self):
        for kind in ('LIGHT', 'BLINDS'):
            for policy in POLICIES:
                e = episode(kind, 'SAFE'); high, low = [t['task_id'] for t in e['task_stream']]
                r = run(e, policy, Slow())
                self.assertTrue(r['audit']['admission_correct'][low])
                self.assertTrue(r['result']['task_correct_action_completed'][low])
                self.assertFalse(r['result']['task_deadline_met'][low])
                self.assertEqual(r['audit']['completed_at_ms'][low] - e['task_stream'][1]['release_at_ms'],
                                 r['result']['task_completion_latency_ms'][low])
                self.assertGreaterEqual(r['result']['task_completion_latency_ms'][low], 7600)
                self.assertFalse(r['result']['task_correct_action_completed'][high])
                self.assertIsNone(r['result']['task_completion_latency_ms'][high])
                self.assertTrue(any(x['type'] == 'action_rejected' and x.get('task_id') == high
                                    for x in r['trace']['events']))

    def test_terminal_rejection_and_main_core_metrics_unchanged(self):
        from homecoord_bench.task_revision.protection_revision import run as old_run
        for kind in ('LIGHT', 'BLINDS'):
            for budget in ('legality', 'equal_response'):
                for condition in ('CONFLICT', 'SAFE'):
                    for policy in POLICIES:
                        e = episode(kind, condition, budget); a, b = run(e, policy), old_run(e, policy)
                        self.assertTrue(all(a['audit']['admission_correct'].values()))
                        for key in ('request_status', 'task_correct_action_completed',
                                    'task_completion_latency_ms', 'task_deadline_met',
                                    'state_constraint_violation_duration_ms'):
                            self.assertEqual(a['result'][key], b['result'][key])

    def test_missing_or_duplicate_admission_evidence_fails(self):
        e = episode('LIGHT', 'SAFE'); r = run(e)
        event = next(x for x in r['trace']['events'] if x['type'] == 'request_admitted')
        bad = deepcopy(r['trace']); bad['events'].remove(event)
        with self.assertRaises(AssertionError): audit(e, bad, r['result'])
        bad = deepcopy(r['trace']); idx = bad['events'].index(event)
        bad['events'].insert(idx, deepcopy(event))
        with self.assertRaises(AssertionError): audit(e, bad, r['result'])

    def test_no_feature_v5_v6_parity(self):
        for e in drafts():
            for policy in POLICIES:
                self.assertEqual(v5(e, FixedProposals(), policy, '', shared_safety_gate=True),
                                 v6(e, FixedProposals(), policy, '', shared_safety_gate=True))

    def test_v5_frozen_bytes_and_manifest_unchanged(self):
        for path, value in frozen_bundle().items():
            self.assertEqual(frozen_serialize(value), (ROOT/path).read_text(encoding='utf-8'))

    def test_v6_reproducible_packet(self):
        data = bundle()
        for path, value in data.items():
            self.assertEqual(serialize(value), (ROOT/path).read_text(encoding='utf-8'))
        m = data['homecoord_bench/task_revision/fixtures/protection_v6_manifest.json']
        for name, digest in m['source_sha256'].items():
            self.assertEqual(digest, hashlib.sha256((ROOT/'homecoord_bench/task_revision'/name).read_bytes()).hexdigest())


if __name__ == '__main__': unittest.main()
