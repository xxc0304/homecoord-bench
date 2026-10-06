import json
import unittest
from unittest.mock import patch
from homecoord_bench.task_revision import resource_synthesis_20261005 as s


class ResourceSynthesisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = s.extract()

    def test_saved_evidence_reproducible(self):
        self.assertEqual(self.e, json.loads((s.ROOT / 'docs/resource_synthesis_20261005/evidence.json').read_text(encoding='utf-8')))

    def test_scope_not_pooled(self):
        self.assertEqual(72, self.e['family_scopes']['F1']['runs'])
        self.assertEqual(32, self.e['family_scopes']['F2']['main_runs'])
        self.assertEqual(192, self.e['family_scopes']['F3']['main_runs'])
        self.assertEqual(32, self.e['family_scopes']['F3']['diagnostic_runs'])
        self.assertFalse(self.e['pooled_cross_family_scores_created'])
        self.assertFalse(self.e['claims_independently_accepted'])

    def test_global_and_individual_disagree_in_each_family(self):
        e = self.e['global_vs_individual_examples']
        a, b = e['F1']['control'], e['F1']['candidate']
        self.assertLess(b['metrics']['whole_house_completion_ms'], a['metrics']['whole_house_completion_ms'])
        self.assertGreater(b['tasks']['water']['completion_ms'], a['tasks']['water']['completion_ms'])
        a, b = e['F2']['simultaneous'], e['F2']['late']
        self.assertLess(b['metrics']['whole_house_completion_ms'], a['metrics']['whole_house_completion_ms'])
        self.assertGreater(b['tasks']['water']['completion_latency_ms'], a['tasks']['water']['completion_latency_ms'])
        for i, ex in enumerate(e['F3']):
            a, b = ex['control_low_resource'], ex['candidate_short_duration']
            self.assertEqual(-120000 if i == 0 else 0, b['all_service_completion_ms']['value'] - a['all_service_completion_ms']['value'])
            self.assertGreater(b['tasks']['water']['wait_ms']['value'], a['tasks']['water']['wait_ms']['value'])

    def test_negative_controls_and_null_macro_preserved(self):
        n = self.e['negative_controls']
        self.assertEqual((36, 12, 36), (n['F1_adequate_all_timely_runs'], n['F1_adequate_identical_gate_constraint_pairs'], n['F1_deadline_pairs_same_actual_time']))
        self.assertEqual((16, 8, 4), (n['F2_adequate_all_timely_runs'], n['F2_adequate_release_water_invariant_pairs'], n['F2_tight_clock_only_pairs']))
        self.assertIsNone(self.e['F3_predefined_summary']['equal_world_factorial_summary']['all_service_completion_ms']['T']['value'])

    def test_changed_source_blocks_extraction(self):
        with patch.object(s, 'sha', return_value='bad'), self.assertRaises(AssertionError):
            s.extract()

    def test_no_trials_and_canonical_F3_reference(self):
        self.assertEqual(0, self.e['new_simulator_runs'])
        self.assertEqual(0, self.e['api_calls'])
        self.assertFalse(self.e['rankings_created'])
        self.assertFalse(self.e['holdout_read'])
        ref = self.e['historical_F3_acceptance_path_encoding_issue']
        self.assertTrue(ref['historical_record_preserved'])
        self.assertTrue(ref['canonical_report_hash_matches_historical_record'])


if __name__ == '__main__':
    unittest.main()

