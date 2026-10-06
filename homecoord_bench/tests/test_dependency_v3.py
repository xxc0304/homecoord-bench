import sys
import json
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.append(str(ROOT.parent))
from homecoord_bench.task_revision.dependency_pilot import episode,run,bundle,CONDITIONS,POLICIES
from homecoord_bench.task_revision.milestone import FixedProposals,drafts
from homecoord_bench.task_revision.event_simulator_v3 import run_event_simulation as v3
from homecoord_bench.task_revision.event_simulator_v2 import run_event_simulation as v2
from homecoord_bench.task_revision.lifecycle_pilot import episode as lifecycle_episode
from homecoord_bench.task_revision.dependency_audit import audit


def at(r,kind,task):
    return [x['timestamp_ms'] for x in r['trace']['events'] if x['type']==kind and x.get('task_id')==task]


class DependencyV3Tests(unittest.TestCase):
    def test_all_nine_conditions_four_policies(self):
        for c in CONDITIONS:
            for p in POLICIES:
                r=run(episode(c),p)
                self.assertEqual(0,r['metrics']['dry_started_without_wash_receipt'])

    def test_request_vs_proposal_vs_completion_vs_action_start(self):
        r=run(episode('EARLY_REQUEST'))
        self.assertEqual([100],at(r,'task_released','dry'))
        self.assertEqual([400],at(r,'proposal_returned','dry'))
        self.assertEqual([4400],at(r,'action_completed','wash'))
        self.assertEqual([4400],at(r,'dependency_ready','dry'))
        self.assertEqual([4500],at(r,'action_started','dry'))
        self.assertEqual([8500],at(r,'action_completed','dry'))
        self.assertEqual(8400,r['metrics']['completion_latency_ms']['dry'])

    def test_late_request_does_not_execute_before_release(self):
        r=run(episode('LATE_REQUEST'))
        self.assertEqual([5400],at(r,'action_started','dry'))
        self.assertEqual(4400,r['metrics']['completion_latency_ms']['dry'])

    def test_early_late_pair_changes_only_dry_release(self):
        a,b=episode('EARLY_REQUEST'),episode('LATE_REQUEST')
        for e in (a,b):
            e.pop('episode_id');e.pop('task_card')
            e['task_stream'][1]['release_at_ms']=0
        self.assertEqual(a,b)

    def test_capacity_pair_changes_only_capacity(self):
        a,b=episode('CAPACITY_TIGHT'),episode('CAPACITY_SAFE')
        for e in (a,b):
            e.pop('episode_id');e.pop('task_card')
            e['home']['resources']['max_power_kw']=0
            e['conflict_rules'][0]['capacity']=0
        self.assertEqual(a,b)

    def test_wash_cancel_blocks_dry_and_ghost_completion(self):
        r=run(episode('CANCEL_WASH'))
        self.assertEqual([],at(r,'action_started','dry'))
        self.assertEqual([],at(r,'action_completed','wash'))
        self.assertEqual([4400],at(r,'completion_discarded','wash'))
        self.assertEqual(['dry'],r['metrics']['blocked_tasks'])
        self.assertIsNone(r['metrics']['completion_latency_ms']['dry'])
        self.assertFalse(r['trace']['final_state']['service']['dry_completed'])

    def test_late_stop_ack_does_not_unblock_cancelled_predecessor(self):
        e=episode('CANCEL_WASH')
        e['simulation']['lifecycle_contracts']['wash']['stop_ack_delay_ms']=4000
        r=run(e)
        self.assertTrue(r['metrics']['completed']['wash'])
        self.assertNotIn('wash',r['metrics']['predecessor_completion_receipts_ms'])
        self.assertEqual([],at(r,'action_started','dry'))

    def test_restart_requires_new_wash_completion(self):
        r=run(episode('RESTART_WASH'))
        self.assertEqual([400,5100],at(r,'action_started','wash'))
        self.assertEqual([9100],at(r,'action_completed','wash'))
        self.assertEqual([9200],at(r,'action_started','dry'))
        self.assertEqual([13200],at(r,'action_completed','dry'))

    def test_invalid_washer_proposal_cannot_fulfill_dependency(self):
        r=run(episode('FAILED_WASH'))
        self.assertFalse(r['metrics']['completed']['wash'])
        self.assertEqual(['dry'],r['metrics']['waiting_tasks'])
        self.assertEqual([],at(r,'action_started','dry'))

    def test_forged_washed_state_not_completion_receipt(self):
        e=episode('FORGED_STATE')
        r=run(e)
        self.assertEqual([4500],at(r,'action_started','dry'))
        control=run(e,enabled=False)
        self.assertEqual([500],at(control,'action_started','dry'))
        self.assertEqual(1,control['metrics']['dry_started_without_wash_receipt'])

    def test_tight_deadline_does_not_hide_infeasibility(self):
        r=run(episode('TIGHT_DEADLINE'))
        self.assertEqual(500,r['metrics']['completion_tardiness_ms']['dry'])

    def test_capacity_competition_is_independent_branch_not_wash_dry(self):
        a=run(episode('CAPACITY_TIGHT'))
        b=run(episode('CAPACITY_SAFE'))
        self.assertEqual([8400],at(a,'action_started','dry'))
        self.assertEqual([4500],at(b,'action_started','dry'))
        self.assertEqual([400],at(a,'action_started','dishes'))

    def test_gate_retry_adds_command_latency_after_capacity_release(self):
        r=run(episode('CAPACITY_TIGHT'),'GateRetryRule')
        self.assertEqual([8500],at(r,'action_started','dry'))
        self.assertTrue(r['metrics']['completed']['dry'])

    def test_no_retry_independent_policy_can_fail_service_not_fake_success(self):
        r=run(episode('CAPACITY_TIGHT'),'IndependentMultiAgent')
        self.assertFalse(r['metrics']['completed']['dry'])
        self.assertIsNone(r['metrics']['completion_latency_ms']['dry'])

    def test_multiple_predecessors_all_must_complete(self):
        e=episode('CAPACITY_SAFE')
        e['task_stream'][1]['depends_on']=['wash','dishes']
        r=run(e)
        self.assertEqual([8500],at(r,'action_started','dry'))

    def test_three_task_dependency_chain(self):
        e=episode('CAPACITY_SAFE')
        e['task_stream'][2]['depends_on']=['dry']
        r=run(e)
        self.assertEqual([8600],at(r,'action_started','dishes'))
        self.assertTrue(all(r['metrics']['completed'].values()))

    def test_cancellation_propagates_through_chain(self):
        e=episode('CAPACITY_SAFE')
        e['task_stream'][2]['depends_on']=['dry']
        base=episode('CANCEL_WASH')
        e['simulation'].update(base['simulation'])
        e['exogenous_events']=base['exogenous_events']
        r=run(e)
        self.assertEqual({'dry','dishes'},set(r['metrics']['blocked_tasks']))
        self.assertEqual([],at(r,'action_started','dishes'))

    def test_dag_cycle_missing_duplicate_self_and_null_rejected(self):
        for bad in ('cycle','missing','duplicate','self','null'):
            e=episode('EARLY_REQUEST')
            if bad=='cycle':e['task_stream'][0]['depends_on']=['dry']
            elif bad=='missing':e['task_stream'][1]['depends_on']=['missing']
            elif bad=='duplicate':e['task_stream'][1]['depends_on']=['wash','wash']
            elif bad=='self':e['task_stream'][1]['depends_on']=['dry']
            else:e['task_stream'][1]['depends_on']=None
            with self.assertRaises(ValueError):run(e)

    def test_reset_washed_between_receipt_and_start_rechecks_tool_condition(self):
        e=episode('EARLY_REQUEST')
        e['exogenous_events']=[{'at_ms':4450,'event':'load_removed','patch':{'laundry.washed':False}}]
        r=run(e)
        self.assertEqual([],at(r,'action_started','dry'))
        self.assertFalse(r['metrics']['completed']['dry'])

    def test_start_at_same_timestamp_as_completion_obeys_queue_order(self):
        e=episode('EARLY_REQUEST')
        e['simulation']['command_latency_ms']=0
        r=run(e)
        self.assertEqual([4300],at(r,'action_completed','wash'))
        self.assertEqual([4300],at(r,'action_started','dry'))

    def test_later_released_predecessor_no_future_service_leak(self):
        e=episode('EARLY_REQUEST')
        e['task_stream'][0]['release_at_ms']=3000
        r=run(e)
        self.assertEqual([7500],at(r,'action_started','dry'))

    def test_unrelated_updates_do_not_unblock_dependency(self):
        e=episode('EARLY_REQUEST')
        e['initial_state']['values']['diagnostic']={'heartbeat':0}
        e['exogenous_events']=[{'at_ms':1000,'event':'heartbeat','patch':{'diagnostic.heartbeat':1}}]
        r=run(e)
        self.assertEqual([4500],at(r,'action_started','dry'))

    def test_v3_without_dependencies_matches_v2_semantics_and_lifecycle(self):
        inputs=drafts()+[lifecycle_episode(k,c) for k in ('CLEAN','RAIN') for c in ('NOEVENT','PRESTART','INFLIGHT','POSTCOMPLETE','UNRELATED')]
        for e in inputs:
            for p in POLICIES:
                with self.subTest(e=e['episode_id'],p=p):
                    self.assertEqual(v2(e,FixedProposals(),p,'',shared_safety_gate=True),
                                     v3(e,FixedProposals(),p,'',shared_safety_gate=True))

    def test_audit_rejects_dry_before_predecessor_completion(self):
        e=episode('FORGED_STATE')
        r=run(e,enabled=False)
        with self.assertRaises(AssertionError):audit(e,r['trace'],r['metrics'],enforce_dependencies=True)

    def test_saved_artifacts_equal_recomputed(self):
        for path,expected in bundle().items():
            self.assertEqual(expected,json.loads((ROOT.parent/path).read_text(encoding='utf-8')))


if __name__=='__main__':unittest.main()
