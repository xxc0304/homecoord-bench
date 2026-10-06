import json,unittest
from collections import Counter
from homecoord_bench.task_revision.aggregation_contract_v2 import build,ROOT,OUT,service_rate_boundary
class AggregationContractV2Tests(unittest.TestCase):
    def test_inventory_unique_primary_and_diagnostic(self):
        b=build();r=b[OUT+'/run_inventory.json'];s=r['slots']
        self.assertEqual(224,len(s));self.assertEqual(224,len({x['canonical_slot_id'] for x in s}))
        self.assertEqual({'primary':192,'diagnostic':32},dict(Counter(x['role'] for x in s)))
        self.assertTrue(all(x['metric_eligibility']=='diagnostic_only' for x in s if x['role']=='diagnostic'))
        self.assertFalse(r['metric_calculation_implemented'])
    def test_contrast_types_separate_and_references_exist(self):
        b=build();s={x['canonical_slot_id']:x for x in b[OUT+'/run_inventory.json']['slots']}
        pairs=b[OUT+'/pair_plan.json']['pairs'];self.assertEqual({'fixed_mode_scheduling':72,'selectable_selector':64,'mode_matched_control':96,'capability_and_selection_intervention':192},dict(Counter(x['contrast_type'] for x in pairs)))
        for p in pairs:
            a,c=s[p['candidate']],s[p['control']]
            self.assertEqual(a['base_world_id'],c['base_world_id'])
            if p['contrast_type']=='fixed_mode_scheduling':
                self.assertEqual(a['authorized_modes_by_task'],c['authorized_modes_by_task'])
            if p['contrast_type']=='selectable_selector':
                self.assertEqual(a['policy'],c['policy']);self.assertEqual(a['authorized_modes_by_task'],c['authorized_modes_by_task'])
    def test_four_cells_and_c4_exact_four_mappings(self):
        b=build();f=b[OUT+'/pair_plan.json']['factorial_cells'];self.assertEqual(24,len(f))
        self.assertTrue(all(len({x[k] for k in ('Y00','Y10','Y01','Y11')})==4 for x in f))
        m=b[OUT+'/c4_replacement_map.json']['mapping'];self.assertEqual(4,len(m))
        self.assertEqual(4,len({x['canonical_slot_id'] for x in m}))
        self.assertTrue(all(not x['old_source']['valid_for_scores'] and x['effective_source']['version']=='v10' for x in m))
    def test_metadata_reproduces(self):
        for p,v in build().items():self.assertEqual(v,json.loads((ROOT/p).read_text(encoding='utf-8')))
    def test_fixed_primary_pair_retains_unstarted_failure(self):
        pairs=build()[OUT+'/pair_plan.json']['pairs']
        fixed=[p for p in pairs if p['contrast_type']=='fixed_mode_scheduling']
        self.assertEqual(72,len(fixed))
        for p in fixed:
            q=p['primary_pair_qualification']
            self.assertFalse(q['requires_complete_actual_vector'])
            self.assertTrue(q['retain_not_started_requests_and_pairs'])
            self.assertNotIn('complete_actual_mode_vector',p['fixed_fields'])
        # Synthetic count reference only: E stays three even if one task never starts.
        a=service_rate_boundary(3,3,3);c=service_rate_boundary(3,2,2)
        self.assertEqual(3,c['timely_service_rate']['required'])
        self.assertAlmostEqual(1/3,a['timely_service_rate']['value']-c['timely_service_rate']['value'])
        self.assertTrue(all('complete_actual_mode_vector' in p['fixed_fields'] for p in pairs if p['contrast_type']=='mode_matched_control'))
    def test_zero_completed_boundary(self):
        r=service_rate_boundary(3,0,0)
        for k in ('service_completion_rate','timely_service_rate'):
            self.assertEqual(0,r[k]['value']);self.assertEqual('ok',r[k]['status'])
        self.assertIsNone(r['timely_among_completed']['value'])
        self.assertEqual('no_completed_requests',r['timely_among_completed']['status'])
    def test_empty_eligibility_boundary(self):
        r=service_rate_boundary(0,0,0)
        self.assertTrue(all(x['value'] is None and x['status']=='no_eligible_requests' for x in r.values()))
    def test_completed_but_all_late_boundary(self):
        r=service_rate_boundary(3,2,0)
        self.assertEqual(0,r['timely_among_completed']['value'])
        self.assertEqual('ok',r['timely_among_completed']['status'])
    def test_invalid_coverage_is_not_null(self):
        for counts in ((3,4,0),(3,1,2),(-1,0,0),(3,0.0,0)):
            with self.assertRaises(ValueError):service_rate_boundary(*counts)
if __name__=='__main__':unittest.main()
