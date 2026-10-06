import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_task_family_split_20260930 import blueprints, build
from probe_c3_multimode_20260930 import PublicModeClient
from probe_architecture_comparison_20261001 import metrics, execute, write, digest
from runtime.architecture_comparison import (
    ARMS, POLICY, ComparisonReleaseProvider, SavedComparisonProvider,
    RequestBudget, BudgetedClient, failure_defer)
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation


class ScriptProvider:
    scripted_latency_ms = 1000

    def decide(self, request, instructions=''):
        tid = request['task']['task_id']
        return PublicModeClient('prepare', {tid: 1000}).decide(request)

    def decide_batch(self, request, instructions=''):
        return {'task_decisions': [{'task_id': c['task']['task_id'], 'decision': self.decide(c)}
                                   for c in request['task_requests']]}


class ArchitectureComparisonTests(unittest.TestCase):
    def episode(self, family='F1', resource='no_competition'):
        card = next(c for c in blueprints() if c['split'] == 'development' and c['family'] == family)
        return build(card, resource, 'late' if family == 'F2' else 'base')

    def run_arm(self, arm, provider=None, family='F1', resource='no_competition'):
        episode = self.episode(family, resource)
        adapter = ComparisonReleaseProvider(arm, provider or ScriptProvider(), 'test-' + arm)
        trace, result = run_event_simulation(episode, adapter, POLICY, '', shared_safety_gate=True)
        adapter.assert_consumed()
        return episode, adapter, trace, result

    def test_three_arm_same_action_clock_identity_and_parallel_devices(self):
        runs = [self.run_arm(arm) for arm in ARMS]
        fields = ('task_service', 'all_deadlines_met', 'task_start_wait_ms', 'task_completion_latency_ms')
        for _, _, trace, result in runs:
            self.assertEqual({1100}, {e['timestamp_ms'] for e in trace['events'] if e['type'] == 'action_started'})
            self.assertTrue(all(result['task_service'].values()))
            for field in fields:
                self.assertEqual(runs[0][3][field], result[field])
        self.assertEqual([1, 3, 3], [len(r[1].batches[0]['calls']) for r in runs])

    def test_information_pool_is_exact_scoped_list_and_local_remains_local(self):
        for arm in ARMS:
            _, adapter, _, _ = self.run_arm(arm)
            batch = adapter.batches[0]
            for call in batch['calls']:
                request = call['request']
                if arm == 'functional_pooled':
                    self.assertEqual(batch['release_group_views'], request['release_group_views'])
                    self.assertEqual(1, len(request['agent']['writable_resources']))
                elif arm == 'central_batch':
                    self.assertEqual(batch['release_group_views'], request['task_requests'])
                else:
                    self.assertNotIn('release_group_views', request)
                for view in batch['release_group_views']:
                    self.assertFalse({'required_action', 'acceptable_actions', 'action_template'} & set(view['task']))

    def test_actual_functional_requests_run_concurrently(self):
        class Concurrent(ScriptProvider):
            def __init__(self):
                self.barrier = Barrier(3)
                self.lock = Lock()
                self.arrivals = 0
            def decide(self, request, instructions=''):
                with self.lock:
                    self.arrivals += 1
                self.barrier.wait(timeout=3)
                return super().decide(request, instructions)
        for arm in ('functional_local', 'functional_pooled'):
            provider = Concurrent()
            _, adapter, _, result = self.run_arm(arm, provider)
            self.assertEqual(3, provider.arrivals)
            self.assertFalse(any(r['error'] for r in adapter.records.values()))
            self.assertTrue(all(result['task_service'].values()))

    def test_actual_return_offsets_not_replaced_by_batch_maximum(self):
        class Measured(ComparisonReleaseProvider):
            def _run_call(self, request, method, started):
                call = super()._run_call(request, method, started)
                call['logical_latency_ms'] = {'laundry': 800, 'meal': 1200, 'dishes': 1600}[request['task']['task_id']]
                return call
        episode = self.episode()
        adapter = Measured('functional_local', ScriptProvider(), 'offset')
        _, result = run_event_simulation(episode, adapter, POLICY, '', shared_safety_gate=True)
        self.assertEqual({'laundry': 800, 'meal': 1200, 'dishes': 1600}, result['model_latency_by_task_ms'])

    def test_late_group_is_fresh_without_future_tasks_and_replay_checks_state(self):
        for arm in ARMS:
            episode, adapter, trace, result = self.run_arm(arm, family='F2', resource='competition')
            early, late = adapter.batches
            self.assertEqual(60000, late['at_ms'])
            self.assertGreater(late['state_version'], early['state_version'])
            self.assertNotIn('water', {c['task']['task_id'] for c in early['release_group_views']})
            self.assertEqual({'water'}, {c['task']['task_id'] for c in late['release_group_views']})
            self.assertNotIn('water', {t['task_id'] for t in early['release_group_views'][0]['state']['coordination_context']['requests']})
            row = {'arm': arm, 'unit_id': adapter.unit_id, 'records': adapter.records, 'batches': adapter.batches}
            rebuilt, second = run_event_simulation(episode, SavedComparisonProvider(row), POLICY, '', shared_safety_gate=True)
            self.assertEqual(trace, rebuilt)
            self.assertEqual(result['task_start_wait_ms'], second['task_start_wait_ms'])
            corrupted = deepcopy(row)
            corrupted['batches'][1]['release_group_views'][0]['state_version'] = -1
            with self.assertRaisesRegex(ValueError, 'release state'):
                run_event_simulation(episode, SavedComparisonProvider(corrupted), POLICY, '', shared_safety_gate=True)

    def test_provider_failure_preserves_all_denominators_and_null_wait(self):
        class Failure(ScriptProvider):
            def decide(self, request, instructions=''):
                if request['task']['task_id'] == 'laundry':
                    raise TimeoutError('synthetic failure')
                return super().decide(request, instructions)
        for arm in ARMS:
            episode, adapter, trace, result = self.run_arm(arm, Failure())
            scored = metrics(trace, result, adapter.records, episode)
            self.assertEqual(3, len(scored['scores']))
            expected_failures = 3 if arm == 'central_batch' else 1
            self.assertEqual(expected_failures, sum(r['local_failure_placeholder'] for r in adapter.records.values()))
            self.assertIsNone(result['task_start_wait_ms']['laundry'])
            self.assertIsNone(result['task_completion_latency_ms']['laundry'])
            self.assertFalse(scored['all_tasks_served'])

    def test_cross_task_tools_in_pooled_context_do_not_expand_authority(self):
        class Unauthorized(ScriptProvider):
            def decide(self, request, instructions=''):
                decision = super().decide(request, instructions)
                if request['task']['task_id'] == 'laundry':
                    decision['actions'][0]['target'] = 'other-device'
                return decision
        for arm in ARMS:
            _, adapter, _, result = self.run_arm(arm, Unauthorized())
            self.assertFalse(result['task_service']['laundry'])
            self.assertEqual(3 if arm == 'central_batch' else 1,
                             sum(r['error'] is not None for r in adapter.records.values()))

    def test_wrong_version_and_duplicate_proposal_are_preserved_failures(self):
        class WrongVersion(ScriptProvider):
            def decide(self, request, instructions=''):
                decision = super().decide(request, instructions)
                decision['actions'][0]['based_on_state_version'] = -100
                return decision
        for arm in ARMS:
            _, adapter, _, result = self.run_arm(arm, WrongVersion())
            self.assertFalse(any(result['task_service'].values()))
            self.assertTrue(all(r['error'] for r in adapter.records.values()))
        class Reused(ScriptProvider):
            def decide(self, request, instructions=''):
                decision = super().decide(request, instructions)
                decision['actions'][0]['proposal_id'] = 'reused'
                return decision
        for arm in ARMS:
            _, adapter, _, _ = self.run_arm(arm, Reused())
            self.assertEqual(3 if arm == 'central_batch' else 2,
                             sum(r['error'] is not None for r in adapter.records.values()))

    def test_explicit_model_off_and_defer_have_no_service_credit(self):
        class NoService(ScriptProvider):
            def decide(self, request, instructions=''):
                if request['task']['task_id'] == 'laundry':
                    return failure_defer()
                decision = super().decide(request, instructions)
                if request['task']['task_id'] == 'meal':
                    decision['actions'][0]['operation'] = 'off'
                return decision
        for arm in ARMS:
            _, adapter, _, result = self.run_arm(arm, NoService())
            self.assertFalse(any(r['local_failure_placeholder'] for r in adapter.records.values()))
            self.assertFalse(result['task_service']['laundry'])
            self.assertFalse(result['task_service']['meal'])
            self.assertIsNone(result['task_start_wait_ms']['meal'])

    def test_failure_uses_budget_no_retry_and_restart_never_refunds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            logger = EventLogger(path, 'test')
            calls = []
            def fail(payload, headers, timeout):
                calls.append(payload)
                raise TimeoutError('synthetic API failure')
            provider = DeepSeekResponsesClient(api_key='dummy', max_attempts=1, transport=fail, logger=logger)
            budget = RequestBudget(1, logger)
            client = BudgetedClient(provider, budget)
            request = {'request_id': 'first', 'episode_id': 'e', 'architecture': 'test'}
            with self.assertRaises(TimeoutError):
                client.decide(request)
            events = [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
            self.assertEqual(1, len(calls))
            self.assertEqual(1, sum(e['event_type'] == 'model_call_failed' for e in events))
            reserved = [e['request_id'] for e in events if e['event_type'] == 'architecture_call_reserved']
            resumed = BudgetedClient(provider, RequestBudget(1, logger, reserved))
            with self.assertRaisesRegex(RuntimeError, 'duplicate'):
                resumed.decide(request)
            with self.assertRaisesRegex(RuntimeError, 'limit'):
                resumed.decide({**request, 'request_id': 'second'})
            self.assertEqual(1, len(calls))

    def test_interrupted_unit_refuses_automatic_resampling(self):
        import probe_architecture_comparison_20261001 as pilot
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / 'manifest.json', {'test': True})
            output = root / 'result.json'
            write(output, {'manifest_sha256': digest(root / 'manifest.json'), 'mode': 'offline',
                           'units': [{'unit_id': 'interrupted', 'status': 'running'}]})
            with patch.object(pilot, 'DIR', root), patch.object(pilot, 'locked', return_value=({}, {})), \
                    patch.object(pilot, 'paths', return_value=(output, root / 'events.jsonl')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted unit'):
                    execute('offline')
            self.assertFalse((root / 'events.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
