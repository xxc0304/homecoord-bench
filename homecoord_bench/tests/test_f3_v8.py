import hashlib
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from homecoord_bench.task_revision.f3_revision import worlds, vectors, episode, inputs, run, bundle, serialize, audit, ModeRule, SELECTORS
from homecoord_bench.task_revision.f3_capability import POLICIES
from homecoord_bench.task_revision.event_simulator_v8 import run_event_simulation
from homecoord_bench.task_revision.review_packet import feasible, verify_witness

ROOT=Path(__file__).resolve().parents[2]


class F3V8Tests(unittest.TestCase):
    def test_all_worlds_fixed_vectors_and_selectable_permissions(self):
        self.assertEqual(8,len(worlds()));self.assertEqual(32,len(inputs()))
        self.assertEqual(24,sum(len(vectors(w)) for w in worlds()))
        for e in inputs():
            self.assertEqual('development',e['split'])
            for t in e['task_stream']:
                authorized=e['mode_capability']['authorized_modes_by_task'][t['task_id']]
                if e['mode_capability']['kind']=='fixed':self.assertEqual(1,len(authorized))
                else:self.assertEqual({x['operation'] for x in t['acceptable_actions']},set(authorized))

    def test_all_192_main_runs_recount_capacity_mode_and_real_completion(self):
        count=0
        for e in inputs():
            for selector in (('low_resource',) if e['mode_capability']['kind']=='fixed' else SELECTORS):
                for p in POLICIES:
                    r=run(e,p,selector);count+=1
                    self.assertEqual('author_recount_passed_not_acceptance',r['audit']['status'])
                    self.assertEqual(r['trace']['agent_requests'],[x['request'] for x in r['calls']])
        self.assertEqual(192,count)

    def test_same_capability_and_information_for_all_four_policies(self):
        for e in inputs():
            first=[run(e,p)['trace']['agent_requests'][0] for p in POLICIES]
            for r in first:r.pop('architecture');r.pop('request_id')
            self.assertTrue(all(r==first[0] for r in first))

    def test_private_labels_raw_goals_and_templates_do_not_enter_request(self):
        e=episode(worlds()[0],'selectable');a=run(e)
        x=deepcopy(e);x['episode_id']=x['base_episode_id']='SECRET-condition-selector'
        x['initial_state']['values']['coordination_context']['secret']='SECRET-context'
        for t in x['task_stream']:t['goal']='SECRET-goal';t['action_template']['estimated_secret']='SECRET-template'
        for t in x['tool_catalog']:t['description']='SECRET-description'
        b=run(x)
        self.assertEqual(a['trace']['agent_requests'],b['trace']['agent_requests'])

    def test_fixed_mode_is_enforced_even_if_provider_proposes_fast(self):
        for w in worlds():
            e=episode(w,'fixed',vectors(w)[0]);r=run(e,diagnostic='forbidden_fast')
            tids={t['task_id'] for t in e['task_stream'] if len(t['acceptable_actions'])>1}
            for tid in tids:
                self.assertFalse(r['result']['task_correct_action_completed'][tid])
                self.assertIsNone(r['result']['task_completion_latency_ms'][tid])
                self.assertTrue(any(x['type']=='action_rejected' and x.get('task_id')==tid
                                    and x['reason']=='mode_not_authorized' for x in r['trace']['events']))
                self.assertFalse(any(x['type']=='mode_selection_committed' and x.get('task_id')==tid for x in r['trace']['events']))

    def test_cost_lies_are_rejected_before_reservation(self):
        r=run(episode(worlds()[0],'selectable'),diagnostic='cost_lie')
        self.assertTrue(all(x is False for x in r['result']['task_correct_action_completed'].values()))
        self.assertFalse(any(x['type']=='action_reserved' for x in r['trace']['events']))
        self.assertTrue(any(x['type']=='action_rejected' and x['reason']=='declared_mode_cost_mismatch' for x in r['trace']['events']))

    def test_off_and_noop_are_not_service_and_low_cost_is_not_success(self):
        for diagnostic in ('off','noop'):
            r=run(episode(worlds()[0],'selectable'),diagnostic=diagnostic)
            self.assertFalse(r['audit']['all_services_completed'])
            self.assertIsNone(r['audit']['all_service_completion_ms'])
            self.assertEqual(0,r['audit']['total_executed_resource_time_units_ms'])
            self.assertTrue(all(v is None for v in r['result']['task_completion_latency_ms'].values()))
            self.assertTrue(all(v is False for v in r['result']['task_deadline_met'].values()))

    def test_commit_before_start_and_retry_preserves_mode(self):
        e=episode(worlds()[0],'selectable');r=run(e,'GateRetryRule','short_duration')
        committed={x['proposal_id']:x for x in r['trace']['events'] if x['type']=='mode_selection_committed'}
        self.assertTrue(any(x['type']=='retry_queued' for x in r['trace']['events']))
        for x in r['trace']['events']:
            if x['type']=='action_started':
                self.assertEqual(committed[x['proposal_id']]['operation'],x['operation'])
                self.assertLess(committed[x['proposal_id']]['timestamp_ms'],x['timestamp_ms'])

    def test_operation_duration_or_mode_commit_tampering_fails_audit(self):
        e=episode(worlds()[0],'selectable');r=run(e)
        for kind in ('mode','duration','commit','score'):
            trace=deepcopy(r['trace']);result=deepcopy(r['result'])
            if kind=='mode':next(x for x in trace['events'] if x['type']=='action_started')['operation']='fast'
            if kind=='duration':next(x for x in trace['events'] if x['type']=='action_started')['duration_ms']+=1
            if kind=='commit':trace['events']=[x for x in trace['events'] if x['type']!='mode_selection_committed']
            if kind=='score':result['task_completion_latency_ms']['laundry']+=1
            with self.subTest(kind=kind),self.assertRaises((AssertionError,KeyError)):
                audit(e,trace,result,r['calls'])

    def test_resource_time_is_actual_integral_not_energy_label(self):
        w=worlds()[0]
        eco=run(episode(w,'fixed',vectors(w)[0]));fast=run(episode(w,'fixed',vectors(w)[-1]))
        self.assertEqual(540000,eco['audit']['task_executed_resource_time_units_ms']['laundry'])
        self.assertEqual(480000,fast['audit']['task_executed_resource_time_units_ms']['laundry'])
        for r in (eco,fast):
            a=r['audit'];self.assertEqual(a['total_executed_resource_time_units_ms'],sum(
                x['units']*(x['end_ms']-x['start_ms']) for x in a['resource_intervals']))
        self.assertLess(fast['audit']['task_executed_resource_time_units_ms']['laundry'],
                        eco['audit']['task_executed_resource_time_units_ms']['laundry'])

    def test_all_physical_mode_witnesses_remain_feasible(self):
        count=0
        for w in worlds():
            c=feasible(w);verify_witness(w,c);count+=len(c['mode_witnesses'])
            self.assertTrue(all(x['status']=='witness_found' for x in c['mode_witnesses']))
        self.assertEqual(24,count)

    def test_unsupported_hooks_inflight_world_changes_and_permissions_fail(self):
        e=episode(worlds()[0],'selectable')
        for mutation in ('event','plan','authority','cost','fixed_set','tool'):
            x=deepcopy(e)
            if mutation=='event':x['exogenous_events']=[{'at_ms':1000,'event':'switch','patch':{}}]
            if mutation=='plan':x['simulation']['released_batch_plan']={}
            if mutation=='authority':x['service_delegation']={}
            if mutation=='cost':x['public_devices'][0]['modes'][0]['duration_ms']+=1
            if mutation=='fixed_set':x['mode_capability']['kind']='fixed'
            if mutation=='tool':x['agents'][0]['tools']=[]
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):run(x)
        class Hook(ModeRule):
            def prepare_release_batch(self,*args):raise AssertionError('must not run')
        with self.assertRaises(ValueError):run_event_simulation(e,Hook(),'ConstraintCoordinator','',shared_safety_gate=True)
        with self.assertRaises(ValueError):run_event_simulation(e,ModeRule(),'ConstraintCoordinator','SECRET',shared_safety_gate=True)

    def test_96_mode_matched_controls_and_separated_contrasts(self):
        data=bundle();c=data['homecoord_bench/task_revision/fixtures/f3_v8/contrasts.json']
        self.assertEqual(96,len(c['mode_matched_controls']))
        self.assertTrue(all(r['core_metrics_equal'] for r in c['mode_matched_controls']))
        self.assertEqual(72,len(c['fixed_mode_scheduling']))
        self.assertEqual(192,len(c['same_policy_mode_selection']))
        self.assertTrue(all('task_start_wait_ms_delta' in r and 'task_completion_tardiness_ms_delta' in r
                            for r in c['same_policy_mode_selection']))

    def test_main_scripts_never_call_offline_oracle(self):
        with patch('homecoord_bench.task_revision.event_simulator_v8.ideal_schedule',side_effect=AssertionError('oracle forbidden')):
            for e in inputs():
                for p in POLICIES:run(e,p)

    def test_same_modes_match_base_execution_metrics(self):
        from runtime.event_simulator import run_event_simulation as base
        for e in inputs():
            for p in POLICIES:
                old=base(e,ModeRule(),p,'',shared_safety_gate=True)[1];new=run(e,p)['result']
                for key in ('task_correct_action_completed','task_completion_latency_ms','task_completion_tardiness_ms','task_deadline_met'):
                    self.assertEqual(old[key],new[key])

    def test_frozen_artifacts_and_sources_reproduce(self):
        data=bundle()
        for p,v in data.items():self.assertEqual(serialize(v),(ROOT/p).read_text(encoding='utf-8'))
        for p,digest in data['homecoord_bench/task_revision/fixtures/f3_v8/manifest.json']['source_sha256'].items():
            self.assertEqual(digest,hashlib.sha256((ROOT/p).read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
