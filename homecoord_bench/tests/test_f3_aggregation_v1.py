import unittest
from copy import deepcopy
from unittest.mock import patch
from homecoord_bench.task_revision.f3_aggregation_v1 import aggregate, recount, compare, four_cell, load, verify_hash, EvidenceError, PREFIX, OUT, value

class F3AggregationV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=aggregate()
    def test_all_rows_pairs_and_cells(self):
        d=self.data
        self.assertEqual(224,len(d['runs']));self.assertEqual(424,len(d['pairs']));self.assertEqual(24,len(d['factorial']))
        self.assertEqual(32,sum(r['identity']['role']=='diagnostic' for r in d['runs'].values()))
        self.assertIsNone(d['adapter_acceptance'])
    def test_fixed_failure_pairs_keep_values_and_no_savings(self):
        fixed=[p for p in self.data['pairs'] if p['contrast_type']=='fixed_mode_scheduling']
        incomplete=[p for p in fixed if any(p[k]['started']<p[k]['required'] for k in ('candidate_coverage','control_coverage'))]
        self.assertEqual(36,len(incomplete))
        for p in incomplete:
            self.assertEqual('ok',p['qualification'])
            self.assertIsNotNone(p['rate_deltas']['timely_service_rate']['value'])
            self.assertIsNone(p['all_service_completion_delta']['value'])
            self.assertIsNone(p['matched_service_cost_saving']['value'])
    def test_incomplete_mechanism_not_filled(self):
        bad=[p for p in self.data['pairs'] if p['qualification']=='incomplete_actual_vector']
        self.assertEqual(12,len(bad));self.assertTrue(all(p['contrast_type']=='mode_matched_control' for p in bad))
        self.assertTrue(all(p['rate_deltas']['timely_service_rate']['value'] is None for p in bad))
    def test_zero_completion_diagnostics(self):
        rows=[r for r in self.data['runs'].values() if r['identity']['diagnostic_id'] in ('off','noop')]
        self.assertEqual(16,len(rows))
        for r in rows:
            self.assertEqual(0,r['rates']['service_completion_rate']['value'])
            self.assertEqual(0,r['rates']['timely_service_rate']['value'])
            self.assertIsNone(r['rates']['timely_among_completed']['value'])
            self.assertEqual('no_completed_requests',r['rates']['timely_among_completed']['status'])
    def test_four_cell_identity_and_missing(self):
        f=four_cell({k:value(v) for k,v in zip(('Y00','Y10','Y01','Y11'),(1,2,3,7))})
        self.assertEqual(3,f['I']['value']);self.assertEqual(f['T']['value'],sum(f[k]['value'] for k in ('S','M','I')))
        for row in self.data['factorial']:
            for values in row['decomposition'].values():
                if values['T']['value'] is not None:self.assertAlmostEqual(values['T']['value'],sum(values[k]['value'] for k in ('S','M','I')))
        with self.assertRaises(EvidenceError):four_cell({'Y00':value(1)})
        self.assertTrue(all(x['value'] is None for x in four_cell({k:value(None) for k in ('Y00','Y10','Y01','Y11')}).values()))
    def test_no_weight_renormalization(self):
        r=self.data['equal_world_factorial_summary']['all_service_completion_ms']['T']
        self.assertLess(r['valid_worlds'],8);self.assertIsNone(r['value']);self.assertEqual(1/8,r['weight_per_world'])
    def test_hash_and_missing_file_fail(self):
        with self.assertRaises(EvidenceError):verify_hash(OUT+'/pair_plan.json','0'*64)
        with self.assertRaises(EvidenceError):load('nonexistent-aggregation-evidence.json')
    def test_receipt_and_score_tamper_rejected(self):
        slot=next(iter(self.data['runs'].values()))['identity']
        ep=next(e for e in load(PREFIX+'inputs.json')['episodes'] if e['episode_id']==slot['config_id'])
        row=load(slot['source_path'])['runs'][int(slot['source_row_pointer'].split('/')[-1])]
        for kind in ('receipt','duration','result','authorization'):
            e=deepcopy(ep);r=deepcopy(row)
            if kind=='receipt':next(x for x in r['trace']['events'] if x['type']=='action_completed')['proposal_id']='fake'
            if kind=='duration':next(x for x in r['trace']['events'] if x['type']=='action_started')['duration_ms']+=1
            if kind=='result':r['result']['task_correct_action_completed']['laundry']=False
            if kind=='authorization':e['mode_capability']['authorized_modes_by_task']['laundry']=['fast']
            with self.subTest(kind=kind),self.assertRaises(EvidenceError):recount(e,r)
    def test_started_uncompleted_wait_stays_observed(self):
        a=deepcopy(next(r for r in self.data['runs'].values() if r['coverage']['completed']==r['coverage']['required']))
        b=deepcopy(a);tid=a['required_ids'][0]
        b['completed'].pop(tid);b['coverage']['completed']-=1
        b['all_service_completion_ms']=value(None,'not_completed')
        b['tasks'][tid]['latency_ms']=value(None,'not_completed');b['tasks'][tid]['tardiness_ms']=value(None,'not_completed')
        p={'contrast_type':'fixed_mode_scheduling','candidate':'a','control':'b','world':'synthetic'}
        result=compare(p,a,b)
        self.assertIsNotNone(result['task_deltas'][tid]['wait_ms']['value'])
        self.assertIsNone(result['task_deltas'][tid]['latency_ms']['value'])
        self.assertIsNone(result['matched_service_cost_saving']['value'])
    def test_diagnostic_cannot_enter_main(self):
        from homecoord_bench.task_revision import f3_aggregation_v1 as module
        original=module.load
        def edited(p,root=module.ROOT):
            x=original(p,root)
            if p==OUT+'/pair_plan.json':
                x=deepcopy(x);diag=next(k for k,r in self.data['runs'].items() if r['identity']['role']=='diagnostic')
                x['pairs'][0]['candidate']=diag
            return x
        with patch.object(module,'load',side_effect=edited),self.assertRaises(EvidenceError):aggregate()
    def test_missing_pair_arm_fails(self):
        from homecoord_bench.task_revision import f3_aggregation_v1 as module
        original=module.load
        def edited(p,root=module.ROOT):
            x=original(p,root)
            if p==OUT+'/pair_plan.json':x=deepcopy(x);x['pairs'][0]['control']='missing-arm'
            return x
        with patch.object(module,'load',side_effect=edited),self.assertRaises(EvidenceError):aggregate()
    def test_saved_artifacts_reproduce(self):
        from homecoord_bench.task_revision.f3_aggregation_v1 import artifacts
        for p,v in artifacts().items():self.assertEqual(v,load(p))

if __name__=='__main__':unittest.main()
