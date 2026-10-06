import sys
import json
import unittest
import hashlib
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.append(str(ROOT))
from homecoord_bench.task_revision.protection_revision import episode,run,bundle,serialize,POLICIES,audit
from homecoord_bench.task_revision.protection_contract import validate
from homecoord_bench.task_revision.milestone import FixedProposals,drafts
from homecoord_bench.task_revision.event_simulator_v5 import run_event_simulation as v5
from homecoord_bench.task_revision.event_simulator_v3 import run_event_simulation as v3


class ProtectionV5Tests(unittest.TestCase):
    def test_all_eight_inputs_all_policies(self):
        for k in ('LIGHT','BLINDS'):
            for b in ('legality','equal_response'):
                for c in ('CONFLICT','SAFE'):
                    for p in POLICIES:
                        r=run(episode(k,c,b),p)
                        self.assertTrue(all(r['audit']['correct_disposition'].values()))
                        self.assertEqual(0,r['audit']['protection_loss_ms'])

    def test_terminal_rejection_has_no_completion_no_call_and_no_revival(self):
        e=episode('LIGHT','CONFLICT');tid=e['task_stream'][1]['task_id'];r=run(e)
        self.assertEqual('rejected_terminal',r['result']['request_status'][tid])
        self.assertIsNone(r['result']['task_completion_latency_ms'][tid])
        self.assertEqual(1200,next(x['timestamp_ms'] for x in r['trace']['events'] if x['type']=='request_terminal_rejected'))
        self.assertTrue(any(x['timestamp_ms']==6000 for x in r['trace']['events']))
        self.assertFalse(any(x.get('task_id')==tid and x['type']=='action_started' for x in r['trace']['events']))

    def test_new_identity_after_expiry_can_execute(self):
        e=episode('BLINDS','CONFLICT');old=e['task_stream'][1];new=deepcopy(old)
        new['task_id']=old['task_id']+'_new';new['release_at_ms']=6500
        e['task_stream'].append(new)
        g=deepcopy(e['action_grounding'][1]);g['task_id']=new['task_id'];e['action_grounding'].append(g)
        e['simulation']['request_disposition_contracts'][new['task_id']]=deepcopy(new['request_contract'])
        r=run(e)
        self.assertEqual('rejected_terminal',r['result']['request_status'][old['task_id']])
        self.assertEqual('completed',r['result']['request_status'][new['task_id']])

    def test_expiry_at_same_release_admits_after_state_update(self):
        e=episode('LIGHT','SAFE');e['task_stream'][1]['release_at_ms']=6000
        r=run(e)
        self.assertEqual('completed',next(iter(r['result']['request_status'].values())))

    def test_late_provider_cannot_turn_release_rejection_into_completion(self):
        class Slow(FixedProposals):last_latency_ms=7000
        r=run(episode('LIGHT','CONFLICT'),provider=Slow())
        self.assertEqual(['rejected_terminal'],list(r['result']['request_status'].values()))
        self.assertFalse(r['result']['task_correct_action_completed']['energy_light'])

    def test_equal_budget_and_single_factor_legality(self):
        for k in ('LIGHT','BLINDS'):
            a,b=episode(k,'CONFLICT','equal_response'),episode(k,'SAFE','equal_response')
            for e in (a,b):
                t=e['task_stream'][1];self.assertEqual(1500,t['completion_deadline_ms']-t['release_at_ms'])
            a,b=episode(k,'CONFLICT'),episode(k,'SAFE')
            for e in (a,b):
                e.pop('episode_id');e['variant'].pop('condition');e['task_stream'][1]['release_at_ms']=0
            self.assertEqual(a,b)

    def test_current_state_view_does_not_include_expiry_or_future_events(self):
        r=run(episode('LIGHT','SAFE'))
        for request in r['trace']['agent_requests']:
            self.assertNotIn('exogenous_events',request)
            self.assertNotIn('6000',json.dumps(request))

    def test_missing_authority_or_ambiguous_contract_rejected(self):
        for change in ('authority','terminal','visible','mixed'):
            e=episode('LIGHT','CONFLICT');tid=e['task_stream'][1]['task_id']
            if change=='authority':e['user_delegations']=[]
            if change=='terminal':e['simulation']['request_disposition_contracts'][tid]['rejection_terminal']=False
            if change=='visible':e['agents'][1]['observable_state']=[]
            if change=='mixed':e['simulation']['environment']={}
            with self.subTest(change=change),self.assertRaises(ValueError):validate(e,'ConstraintCoordinator',True)

    def test_tampered_status_or_completion_rejected(self):
        e=episode('LIGHT','CONFLICT');r=run(e);tid=e['task_stream'][1]['task_id']
        bad=deepcopy(r['result']);bad['request_status'][tid]='completed'
        with self.assertRaises(AssertionError):audit(e,r['trace'],bad)
        bad=deepcopy(r['result']);bad['task_correct_action_completed'][tid]=True
        with self.assertRaises(AssertionError):audit(e,r['trace'],bad)

    def test_invalid_boolean_and_duplicate_request_identity_rejected(self):
        e=episode('LIGHT','CONFLICT');e['initial_state']['values']['study']['reading_active']='true'
        with self.assertRaises(ValueError):run(e)
        e=episode('LIGHT','CONFLICT');e['task_stream'].append(deepcopy(e['task_stream'][1]))
        with self.assertRaises(ValueError):run(e)

    def test_feature_absent_v3_v5_parity(self):
        for e in drafts():
            for p in POLICIES:
                self.assertEqual(v3(e,FixedProposals(),p,'',shared_safety_gate=True),v5(e,FixedProposals(),p,'',shared_safety_gate=True))

    def test_frozen_outputs_and_source_hashes(self):
        data=bundle()
        for name,value in data.items():self.assertEqual(serialize(value),(ROOT/name).read_text(encoding='utf-8'))
        m=data['homecoord_bench/task_revision/fixtures/protection_v5_manifest.json']
        for name,digest in m['source_sha256'].items():
            self.assertEqual(digest,hashlib.sha256((ROOT/'homecoord_bench/task_revision'/name).read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
