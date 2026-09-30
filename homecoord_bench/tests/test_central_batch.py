import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_task_family_split_20260930 import blueprints, build
from probe_central_batch_20260930 import ScriptBatchProvider, CountingSpecialists
from runtime.central_batch import (build_batch_request, assert_batch_decision, ReleaseBatchAdapter, CentralBatchDeepSeekClient)
from runtime.event_simulator import run_event_simulation

class CentralBatchTests(unittest.TestCase):
    def episode(self, family='F1', resource='no_competition'):
        card = next(c for c in blueprints() if c['split'] == 'development' and c['family'] == family)
        return build(card, resource, 'late' if family == 'F2' else 'base')
    def modes(self, episode):
        return {t['task_id']: t['action_template']['operation'] for t in episode['task_stream']}
    def request_and_decision(self):
        e = self.episode()
        request = build_batch_request(e, 0, e['initial_state']['values'], e['initial_state']['version'])
        decision = ScriptBatchProvider(self.modes(e)).decide_batch(request)
        return e, request, decision

    def test_one_batch_call_and_parallel_device_starts(self):
        e = self.episode()
        provider = ScriptBatchProvider(self.modes(e))
        adapter = ReleaseBatchAdapter(provider)
        trace, result = run_event_simulation(e, adapter, 'ConstraintCoordinator', '', shared_safety_gate=True)
        adapter.assert_consumed()
        self.assertEqual(1, provider.calls)
        self.assertEqual('CentralBatchProposer', result['proposal_architecture'])
        self.assertEqual({1100}, {x['timestamp_ms'] for x in trace['events'] if x['type'] == 'action_started'})
        self.assertEqual({t['task_id']: 1000 for t in e['task_stream']}, result['model_latency_by_task_ms'])

    def test_late_batch_is_built_from_live_release_state_without_future(self):
        e = self.episode('F2', 'competition')
        provider = ScriptBatchProvider(self.modes(e))
        adapter = ReleaseBatchAdapter(provider)
        run_event_simulation(e, adapter, 'DeadlineAwareCoordinator', '', shared_safety_gate=True)
        adapter.assert_consumed()
        self.assertEqual(2, provider.calls)
        early, late = (b['request'] for b in adapter.batches)
        self.assertNotIn('water', {r['task']['task_id'] for r in early['task_requests']})
        self.assertEqual({'water'}, {r['task']['task_id'] for r in late['task_requests']})
        self.assertEqual(60000, late['current_time_ms'])
        self.assertGreater(late['state_version'], early['state_version'])
        for request in (early, late):
            self.assertNotIn('state', request)  # no raw globally visible state
            for child in request['task_requests']:
                self.assertFalse(any(k in child['task'] for k in ('required_action','acceptable_actions','action_template')))
        self.assertNotIn('water', {r['task_id'] for r in early['task_requests'][0]['state']['coordination_context']['requests']})

    def test_reject_missing_duplicate_future_tasks_and_proposal_ids(self):
        e, request, decision = self.request_and_decision()
        for mode in ('missing', 'duplicate_task', 'future', 'duplicate_proposal'):
            bad = deepcopy(decision)
            if mode == 'missing':
                bad['task_decisions'].pop()
            elif mode == 'duplicate_task':
                bad['task_decisions'][1]['task_id'] = bad['task_decisions'][0]['task_id']
            elif mode == 'future':
                bad['task_decisions'][1]['task_id'] = 'unreleased_future'
            else:
                bad['task_decisions'][1]['decision']['actions'][0]['proposal_id'] = bad['task_decisions'][0]['decision']['actions'][0]['proposal_id']
            with self.assertRaises(ValueError):
                assert_batch_decision(bad, request, e)

    def test_cross_task_tools_and_wrong_snapshot_are_rejected(self):
        e, request, decision = self.request_and_decision()
        bad = deepcopy(decision)
        bad['task_decisions'][0]['decision']['actions'][0]['target'] = 'water_device'
        with self.assertRaisesRegex(ValueError, 'not authorized'):
            assert_batch_decision(bad, request, e)
        bad = deepcopy(decision)
        bad['task_decisions'][0]['decision']['actions'][0]['based_on_state_version'] = 999
        with self.assertRaisesRegex(ValueError, 'state version'):
            assert_batch_decision(bad, request, e)

    def test_explicit_defer_and_off_are_not_scored_as_service(self):
        class NoService(ScriptBatchProvider):
            def decide_batch(self, request, instructions=''):
                result = super().decide_batch(request, instructions)
                result['task_decisions'][0]['decision'].update(response_type='defer', actions=[], reason_code='awaiting_state')
                result['task_decisions'][1]['decision']['actions'][0]['operation'] = 'off'
                return result
        e = self.episode()
        provider = ReleaseBatchAdapter(NoService(self.modes(e)))
        _, result = run_event_simulation(e, provider, 'DeadlineAwareCoordinator', '', shared_safety_gate=True)
        self.assertFalse(result['task_service']['laundry'])
        self.assertFalse(result['task_service']['meal'])
        self.assertIsNone(result['task_start_wait_ms']['laundry'])
        self.assertIsNone(result['task_start_wait_ms']['meal'])

    def test_real_api_adapter_fake_transport_uses_batch_schema_and_budget(self):
        e, request, decision = self.request_and_decision()
        captured = []
        def transport(payload, _headers, _timeout):
            captured.append(payload)
            return {'id': 'fake', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(decision)}]}]}
        provider = CentralBatchDeepSeekClient(api_key='dummy', transport=transport)
        result = provider.decide_batch(request)
        self.assertEqual(decision, result)
        self.assertEqual('homecoord_release_batch', captured[0]['text']['format']['name'])
        self.assertEqual(1200 * len(request['task_requests']), captured[0]['max_output_tokens'])
        self.assertEqual(1, len(captured))
        self.assertFalse(captured[0]['store'])

    def test_old_serializing_central_executor_is_not_accepted_for_new_adapter(self):
        e = self.episode()
        adapter = ReleaseBatchAdapter(ScriptBatchProvider(self.modes(e)))
        with self.assertRaisesRegex(ValueError, 'does not support'):
            run_event_simulation(e, adapter, 'CentralSingleAgent', '')

    def test_proposal_identity_cannot_be_reused_by_later_batch(self):
        class ReusedIdentity(ScriptBatchProvider):
            prior = None
            def decide_batch(self, request, instructions=''):
                result = super().decide_batch(request, instructions)
                action = result['task_decisions'][0]['decision']['actions'][0]
                if self.prior is None:
                    self.prior = action['proposal_id']
                else:
                    action['proposal_id'] = self.prior
                return result
        e = self.episode('F2')
        adapter = ReleaseBatchAdapter(ReusedIdentity(self.modes(e)))
        with self.assertRaisesRegex(ValueError, 'across release batches'):
            run_event_simulation(e, adapter, 'ConstraintCoordinator', '', shared_safety_gate=True)

if __name__ == '__main__':
    unittest.main()
