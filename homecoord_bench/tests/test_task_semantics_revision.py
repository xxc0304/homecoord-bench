import sys
import json
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from homecoord_bench.task_revision.milestone import (
    c1, c4, drafts, inventory, verify, FixedProposals, score, audit_trace, bundle, ROOT,
)
from homecoord_bench.runtime.episode_validation import validate_event_episode
from homecoord_bench.runtime.event_simulator import run_event_simulation


class TaskSemanticsRevisionTests(unittest.TestCase):
    def test_four_structures_fourteen_configs_not_fourteen_structures(self):
        episodes = drafts()
        self.assertEqual(14, len(episodes))
        self.assertEqual(4, len({e['variant']['structure'] for e in episodes}))
        self.assertEqual(14, len({e['episode_id'] for e in episodes}))
        for e in episodes:
            self.assertEqual([], validate_event_episode(e))

    def test_all_expected_semantics_in_shared_runtime(self):
        for e in drafts():
            with self.subTest(episode=e['episode_id']):
                verify(e)

    def test_c1_pairs_change_only_release_in_execution_input(self):
        for kind in ('LIGHT', 'BLINDS'):
            a, b = c1(kind, 'CONFLICT'), c1(kind, 'SAFE')
            for e in (a, b):
                for k in ('episode_id', 'variant', 'task_card'):
                    e.pop(k)
                e['task_stream'][1]['release_at_ms'] = 0
            self.assertEqual(a, b)

    def test_c1_is_persistent_protection_not_overlapping_commands(self):
        for kind in ('LIGHT', 'BLINDS'):
            e = c1(kind, 'CONFLICT')
            check = verify(e)
            events = check['trace']['events']
            high, low = [t['task_id'] for t in e['task_stream']]
            high_finish = next(x['timestamp_ms'] for x in events if x['type'] == 'action_completed' and x['task_id'] == high)
            self.assertLess(high_finish, e['task_stream'][1]['release_at_ms'])
            self.assertTrue(check['score']['resolution_correct'])
            self.assertFalse(check['score']['action_completed'][low])
            self.assertIsNone(check['score']['completion_latency_ms'][low])

    def test_c1_safe_control_services_both_requests(self):
        for kind in ('LIGHT', 'BLINDS'):
            self.assertTrue(all(verify(c1(kind, 'SAFE'))['score']['action_completed'].values()))

    def test_c1_missing_guard_rejected_by_tool_contract_not_rewarded(self):
        e = c1('BLINDS', 'CONFLICT')
        e['task_stream'][1]['action_template']['requires'] = []
        trace, result = run_event_simulation(e, FixedProposals(), 'IndependentMultiAgent', '', shared_safety_gate=True)
        self.assertFalse(score(e, trace, result)['resolution_correct'])
        self.assertFalse(result['task_correct_action_completed'][e['task_stream'][1]['task_id']])

    def test_external_events_never_write_service_goal(self):
        for e in drafts():
            for event in e['exogenous_events']:
                self.assertFalse(any(p.startswith('service.') for p in event['patch']))

    def test_c4_signal_timing_only_changes_events(self):
        for kind in ('CLEAN', 'RAIN'):
            a, b = c4(kind, 'NOEVENT'), c4(kind, 'INFLIGHT')
            for e in (a, b):
                for k in ('episode_id', 'variant', 'task_card', 'exogenous_events'):
                    e.pop(k)
            self.assertEqual(a, b)

    def test_c4_inflight_completion_cannot_hide_harm(self):
        for kind in ('CLEAN', 'RAIN'):
            e = c4(kind, 'INFLIGHT')
            s = verify(e)['score']
            self.assertTrue(s['action_completed'][e['task_stream'][0]['task_id']])
            self.assertEqual(2400, s['harm_duration_ms'])
            self.assertFalse(s['work_process_valid_completed'])
            self.assertIsNone(s['recovery_completed'])

    def test_c4_unrelated_state_version_update_not_stale_rejection(self):
        for kind in ('CLEAN', 'RAIN'):
            s = verify(c4(kind, 'UNRELATED'))['score']
            self.assertTrue(s['work_process_valid_completed'])
            self.assertEqual(0, s['in_flight_invalidations'])

    def test_recovery_contracts_are_distinct_and_unimplemented(self):
        clean = c4('CLEAN', 'INFLIGHT')['task_card']['lifecycle']
        rain = c4('RAIN', 'INFLIGHT')['task_card']['lifecycle']
        self.assertTrue(clean['restart_from_zero'])
        self.assertFalse(rain['restart_from_zero'])
        self.assertIn('NOT implemented', clean['runtime_support'])

    def test_inventory_canonical_decisions_and_holdout_exclusion(self):
        inv = inventory()
        self.assertEqual(20, len(inv['canonical_decisions']))
        self.assertEqual(24, len(inv['heldout_unopened_paths']))
        self.assertFalse(any('prospective_test' in r['path'] for r in inv['artifacts']))
        self.assertEqual(24, inv['decision_counts']['C3_development_author_contract'])
        self.assertEqual(12, inv['decision_counts']['frozen_architecture_input_snapshot_not_new_task'])

    def test_independent_audit_rejects_masked_harm(self):
        e = c4('CLEAN', 'INFLIGHT')
        check = verify(e)
        wrong = deepcopy(check['score'])
        wrong['harm_duration_ms'] = 0
        with self.assertRaises(AssertionError):
            audit_trace(e, check['trace'], wrong)

    def test_independent_audit_rejects_unsupported_completion(self):
        e = c4('RAIN', 'PRESTART')
        check = verify(e)
        wrong = deepcopy(check['score'])
        wrong['action_completed'][e['task_stream'][0]['task_id']] = True
        with self.assertRaises(AssertionError):
            audit_trace(e, check['trace'], wrong)

    def test_saved_artifacts_match_recomputed_development_checks(self):
        for relative, expected in bundle().items():
            path = ROOT.parent / relative
            with self.subTest(path=relative):
                self.assertEqual(expected, json.loads(path.read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
