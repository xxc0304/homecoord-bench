import hashlib
import unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
from homecoord_bench.task_revision.f2_revision import inputs, run, bundle, prefix, counterfactual, serialize, PublicProposals
from homecoord_bench.task_revision.f2_information import POLICIES, build_agent_request
from homecoord_bench.task_revision.event_simulator_v7 import run_event_simulation
from homecoord_bench.task_revision.review_packet import feasible, verify_witness

ROOT = Path(__file__).resolve().parents[2]


class F2V7Tests(unittest.TestCase):
    def test_eight_development_inputs_and_own_release_deadline_pairs(self):
        episodes = inputs(); self.assertEqual(8,len(episodes))
        for e in episodes:
            self.assertEqual('development',e['split'])
            for t in e['task_stream']:
                self.assertGreater(t['completion_deadline_ms'],t['release_at_ms'])
        for base in {e['base_episode_id'] for e in episodes}:
            for arm in ('competition','no_competition'):
                pair = [e for e in episodes if e['base_episode_id']==base and e['pairing']['resource_arm']==arm]
                self.assertEqual([{t['task_id']:t['completion_deadline_ms']-t['release_at_ms'] for t in e['task_stream']} for e in pair][0],
                                 [{t['task_id']:t['completion_deadline_ms']-t['release_at_ms'] for t in e['task_stream']} for e in pair][1])

    def test_all_inputs_all_policies_and_actual_capture(self):
        for e in inputs():
            for p in POLICIES:
                r = run(e,p)
                self.assertEqual(r['trace']['agent_requests'],[c['request'] for c in r['calls']])
                self.assertEqual('author_verified_not_acceptance',r['audit']['status'])
                for request in r['trace']['agent_requests']:
                    self.assertEqual('F2-public-home',request['episode_id'])
                    self.assertNotIn('action_template',request['task'])

    def test_all_48_counterfactual_full_inputs_and_online_prefixes(self):
        for e in inputs():
            if e['pairing']['temporal_arm'] != 'late': continue
            before = min(t['release_at_ms'] for t in e['task_stream'] if t['release_at_ms']>0)
            for p in POLICIES:
                a = prefix(run(e,p),before)
                for case in ('different_arrival','different_request','no_future_request'):
                    self.assertEqual(a,prefix(run(counterfactual(e,case),p),before))

    def test_same_timestamp_publication_is_atomic_for_all_policies(self):
        e = next(e for e in inputs() if e['pairing']['temporal_arm']=='simultaneous')
        expected = {t['task_id'] for t in e['task_stream']}
        for p in POLICIES:
            for r in run(e,p)['trace']['agent_requests']:
                self.assertEqual(expected,{t['task_id'] for t in r['state']['coordination_context']['requests']})

    def test_untrusted_channels_and_extra_kwargs_cannot_enter_request(self):
        e = next(e for e in inputs() if e['pairing']['temporal_arm']=='late')
        changed = counterfactual(e,'different_request')
        task = e['task_stream'][0]; agent = e['agents'][0]
        changed['constraints'] = [{'secret':'SECRET-future-constraint'}]
        changed['simulation']['secret'] = 'SECRET-future-plan'
        a = build_agent_request(e,agent,task,architecture='ConstraintCoordinator',current_time_ms=0)
        b = build_agent_request(changed,agent,task,architecture='ConstraintCoordinator',current_time_ms=0,
                                request_id='SECRET-private-id',include_evaluation_hints=True,
                                pending_proposals=[{'secret':'SECRET-future-proposal'}])
        self.assertEqual(a,b)
        # Unsupported plans/constraints are rejected by the execution boundary,
        # even though the whitelist itself never serializes those channels.
        with self.assertRaises(ValueError): run(changed)

    def test_provider_hook_and_external_instruction_rejected(self):
        class Hook(PublicProposals):
            def prepare_release_batch(self,*args): raise AssertionError('must not run')
        e=inputs()[0]
        with self.assertRaises(ValueError): run(e,provider=Hook())
        with self.assertRaises(ValueError):
            run_event_simulation(e,PublicProposals(),'ConstraintCoordinator','SECRET',shared_safety_gate=True)

    def test_unsupported_oracle_plans_and_cost_mismatch_rejected(self):
        e=inputs()[0]
        for p in ('CentralSingleAgent','RobustReserveCoordinator','ObservedTaskFeasibilityCoordinator'):
            with self.assertRaises(ValueError): run(e,p)
        for variant in ('plan','static_extra','cost','delegation','conflict'):
            x=deepcopy(e)
            if variant=='plan': x['simulation']['released_batch_plan']={}
            if variant=='static_extra': x['public_devices'][0]['secret']='SECRET'
            if variant=='cost': x['public_devices'][0]['duration_ms']+=1
            if variant=='delegation': x['nonpreemptive_delegation']={}
            if variant=='conflict': x['conflict_rules'].append({'type':'C1'})
            with self.subTest(variant=variant),self.assertRaises(ValueError):run(x)

    def test_online_methods_never_call_offline_oracle(self):
        with patch('homecoord_bench.task_revision.event_simulator_v7.ideal_schedule',side_effect=AssertionError('oracle forbidden')):
            for e in inputs():
                for p in POLICIES:run(e,p)

    def test_offline_witnesses_valid_but_not_online_guarantee(self):
        for e in inputs():
            certificate=feasible(e); verify_witness(e,certificate)
            self.assertTrue(all(c['status']=='witness_found' for c in certificate['mode_witnesses']))
        e=next(e for e in inputs() if e['pairing']=={'resource_arm':'competition','temporal_arm':'late'})
        self.assertFalse(run(e,'DeadlineAwareCoordinator')['result']['all_deadlines_met'])

    def test_no_action_remains_false_null_and_queued_completion_is_real(self):
        class NoAction(PublicProposals):
            def decide(self,r,instructions):
                d={'response_type':'noop','actions':[],'accepted_proposal_ids':[],
                   'rejected_proposal_ids':[],'defer_until_ms':None,'reason_code':'no_applicable_action'}
                self.calls.append({'request':deepcopy(r),'decision':deepcopy(d)});return d
        r=run(inputs()[0],provider=NoAction())
        self.assertTrue(all(v is False for v in r['result']['task_correct_action_completed'].values()))
        self.assertTrue(all(v is None for v in r['result']['task_completion_latency_ms'].values()))
        e=next(e for e in inputs() if e['pairing']=={'resource_arm':'competition','temporal_arm':'simultaneous'})
        r=run(e,'DeadlineAwareCoordinator')
        self.assertTrue(r['result']['all_deadlines_met'])
        self.assertTrue(any(v>400 for v in r['result']['task_start_wait_ms'].values()))

    def test_versioned_engine_has_only_documented_base_changes(self):
        source=(ROOT/'homecoord_bench/runtime/event_simulator.py').read_text(encoding='utf-8')
        expected=source.replace('"""Deterministic discrete-event simulator for asynchronous home coordination.',
                                '"""F2 v7: frozen base event engine with whitelist import and scope validation.')
        expected=expected.replace('from runtime.protocol import assert_agent_decision, build_agent_request',
                                   'from runtime.protocol import assert_agent_decision\nfrom homecoord_bench.task_revision.f2_information import build_agent_request, validate_f2')
        expected=expected.replace('    validation_errors = validate_event_episode(episode)',
                                   '    validate_f2(episode, decision_provider, policy, instructions, shared_safety_gate,\n                synthetic_latency, coordination_delay_ms)\n    validation_errors = validate_event_episode(episode)')
        self.assertEqual(expected,(ROOT/'homecoord_bench/task_revision/event_simulator_v7.py').read_text(encoding='utf-8'))

    def test_core_script_metrics_match_base_engine_without_changing_frozen_results(self):
        from runtime.event_simulator import run_event_simulation as base
        for e in inputs():
            for p in POLICIES:
                before=base(e,PublicProposals(),p,'',shared_safety_gate=True)[1]
                after=run(e,p)['result']
                for key in ('task_correct_action_completed','task_start_wait_ms',
                            'task_completion_latency_ms','task_completion_tardiness_ms',
                            'task_deadline_met','all_deadlines_met'):
                    self.assertEqual(before[key],after[key])

    def test_frozen_packet_and_source_hashes_reproduce(self):
        data=bundle()
        for p,v in data.items():self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
        for p,digest in data['homecoord_bench/task_revision/fixtures/f2_v7/manifest.json']['source_sha256'].items():
            self.assertEqual(digest,hashlib.sha256((ROOT/p).read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
