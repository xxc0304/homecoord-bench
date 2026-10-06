import sys
import json
import hashlib
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
from homecoord_bench.task_revision.phase_b_packet import approved_inputs,bundle,recount,serialize,OUT,REVIEW,Capture,PublicModeClient,v1


class PhaseBPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=bundle()
        cls.first=next(v for k,v in cls.data.items() if '/traces/' in k)

    def test_scope_and_all_rows_retained(self):
        index=self.data[f'{OUT}/index.json']
        self.assertEqual(13,index['configurations']);self.assertEqual(92,index['reproductions'])
        self.assertEqual(92,sum(x['runs'] for x in index['entries']))
        self.assertEqual(13,len(approved_inputs()))
        self.assertTrue(all(x['acceptance'] is None for x in index['entries']))

    def test_saved_byte_reproduction_and_source_hashes(self):
        for path,value in self.data.items():self.assertEqual(serialize(value),(ROOT/path).read_text(encoding='utf-8'))
        manifest=self.data[f'{OUT}/manifest.json']
        for key in ('artifact_sha256','source_sha256','historical_result_sha256'):
            for path,digest in manifest[key].items():self.assertEqual(digest,hashlib.sha256((ROOT/path).read_bytes()).hexdigest())
        self.assertFalse(manifest['independent_dual_review_complete'])
        self.assertIsNone(manifest['implementation_acceptance'])

    def test_tampered_metric_is_rejected(self):
        e=self.first['episode'];r=deepcopy(self.first['runs'][0])
        tid=e['task_stream'][0]['task_id'];r['reported_result']['task_completion_latency_ms'][tid]+=1
        with self.assertRaises(AssertionError):recount(e,r['trace'],r['reported_result'],r['calls'])

    def test_tampered_grounding_and_proposal_identity_are_rejected(self):
        e=self.first['episode']
        for mutation in ('duration','proposal'):
            r=deepcopy(self.first['runs'][0])
            kind='action_started' if mutation=='duration' else 'action_completed'
            event=next(x for x in r['trace']['events'] if x['type']==kind)
            if mutation=='duration':event['duration_ms']+=1
            else:event['proposal_id']='unmatched'
            with self.subTest(mutation=mutation),self.assertRaises((AssertionError,KeyError)):
                recount(e,r['trace'],r['reported_result'],r['calls'])

    def test_forged_state_cannot_replace_completion_receipt(self):
        data=self.data[f'{OUT}/traces/DEP-LAUNDRY-FORGED_STATE.json'];r=deepcopy(data['runs'][0])
        r['trace']['events']=[x for x in r['trace']['events'] if not(x['type']=='action_completed' and x['task_id']=='wash')]
        with self.assertRaises(AssertionError):recount(data['episode'],r['trace'],r['reported_result'],r['calls'])

    def test_unserved_capacity_case_keeps_false_and_null(self):
        data=self.data[f'{OUT}/traces/DEP-LAUNDRY-CAPACITY_TIGHT.json']
        r=next(x for x in data['runs'] if x['policy']=='IndependentMultiAgent')
        metrics=r['independent_event_recount']['recomputed']
        self.assertFalse(metrics['task_correct_action_completed']['dry'])
        self.assertIsNone(metrics['task_completion_latency_ms']['dry'])
        self.assertFalse(r['reported_result']['all_deadlines_met'])

    def test_no_holdout_reads_and_archived_review_fallback(self):
        original=Path.read_text;exists=Path.exists
        def guarded(p,*args,**kwargs):
            self.assertNotIn('prospective_test',p.parts)
            return original(p,*args,**kwargs)
        def without_original(p):return False if p==REVIEW else exists(p)
        with patch.object(Path,'read_text',guarded),patch.object(Path,'exists',without_original):
            fallback=bundle()
        self.assertEqual(self.data,fallback)

    def test_legal_off_is_not_requested_service(self):
        class OffOnly(PublicModeClient):
            def decide(self,request,instructions=''):
                d=super().decide(request,instructions)
                tool=next(t for t in request['available_actions'] if t['operation']=='off')
                d['actions'][0].update(operation='off',estimated_duration_ms=tool['cost_contract']['duration_ms'],estimated_power_kw=0)
                return d
        e=self.first['episode'];p=Capture(OffOnly('prepare',{t['task_id']:800 for t in e['task_stream']}))
        trace,result=v1(e,p,'ConstraintCoordinator','',shared_safety_gate=True)
        checked=recount(e,trace,result,p.calls)
        self.assertFalse(any(checked['recomputed']['task_correct_action_completed'].values()))
        self.assertTrue(all(x is None for x in checked['recomputed']['task_completion_latency_ms'].values()))


if __name__=='__main__':unittest.main()
