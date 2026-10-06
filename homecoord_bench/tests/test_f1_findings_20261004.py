import json
import unittest
from homecoord_bench.task_revision.f1_findings_20261004 import ROOT, extract


class F1FindingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = extract()

    def test_saved_evidence_reproducible(self):
        saved = json.loads((ROOT / 'docs/f1_findings_20261004/evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(self.evidence, saved)

    def test_tight_base_return_order_and_late_identity(self):
        x = self.evidence
        self.assertEqual(4, len(x['late_task_records']))
        self.assertTrue(all(t['task_id'] == 'water' for t in x['late_task_records']))
        self.assertEqual([[5,4,4],[5,4,4],[5,5,5]], [r['timely_per_order'] for r in x['F1_02_tight_base_by_order']])

    def test_whole_house_and_individual_tradeoff(self):
        table = self.evidence['F1_02_tight_base_by_order']; a, b = table[:2]
        self.assertEqual(-239800, b['whole_house_completion_per_order_ms'][2]-a['whole_house_completion_per_order_ms'][2])
        self.assertEqual(240200, b['water_completion_per_order_ms'][2]-a['water_completion_per_order_ms'][2])

    def test_limits_and_negative_controls(self):
        x = self.evidence
        self.assertEqual(36, x['adequate_capacity_all_timely_runs'])
        self.assertEqual(36, len(x['deadline_pairs_same_actual_time']))
        self.assertEqual(12, x['adequate_gate_vs_constraint_identical_task_time_pairs'])
        self.assertEqual(18, x['four_cell_full_K_groups'])
        self.assertFalse(x['rankings_or_inferential_statistics_created'])
        self.assertEqual(0, x['api_calls'])
        self.assertEqual(0, x['simulator_runs'])


if __name__ == '__main__':
    unittest.main()
