import json
import unittest
from unittest.mock import patch

from homecoord_bench.task_revision import f2_findings_20261005 as f


class F2FindingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = f.extract()
        cls.rows = {r['slot_id']: r for r in cls.e['run_evidence']}

    def test_saved_evidence_reproducible(self):
        saved = json.loads((f.ROOT / 'docs/f2_findings_20261005/evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(self.e, saved)

    def test_full_scope_failure_and_delay_not_merged(self):
        self.assertEqual({'runs': 32, 'pairs': 72, 'four_cells': 8, 'diagnostic_prefix_pairs': 48}, self.e['scope'])
        self.assertEqual(8, len(self.e['failed_task_records']))
        self.assertEqual(10, len(self.e['late_task_records']))
        self.assertTrue(all(x['completion_ms'] is None for x in self.e['failed_task_records']))
        self.assertTrue(all(x['completed'] and x['tardiness_ms'] > 0 for x in self.e['late_task_records']))
        self.assertEqual(0, self.e['executed_capacity_violating_runs'])

    def test_capacity_and_own_clock_negative_controls(self):
        self.assertEqual(16, self.e['adequate_all_timely_runs'])
        self.assertEqual(8, len(self.e['invariant_water_adequate_release_pairs']))
        for x in self.e['invariant_water_adequate_release_pairs']:
            self.assertEqual(0, x['water_completion_latency']['effects']['right_minus_left'])
        for x in self.e['clock_only_tight_release_pairs']:
            self.assertTrue(x['all_task_absolute_execution_identical'])
            self.assertEqual(-x['release_shift_ms'], x['water_completion_latency']['effects']['right_minus_left'])
            self.assertEqual(0, x['whole_house']['effects']['right_minus_left'])

    def test_deadline_early_water_and_house_tradeoff(self):
        self.assertEqual(2, len(self.e['worsened_water_tight_release_pairs']))
        by_base = {'01': (720000, 120000), '02': (420000, -60000)}
        for base, (response, house) in by_base.items():
            sim = self.rows[f'F2R1-D-F2-{base}-competition-simultaneous|DeadlineAwareCoordinator']
            late = self.rows[f'F2R1-D-F2-{base}-competition-late|DeadlineAwareCoordinator']
            self.assertTrue(sim['tasks']['water']['timely'])
            self.assertFalse(late['tasks']['water']['timely'])
            self.assertEqual(3, late['subsets']['early']['denominators']['timely'])
            self.assertEqual(response, late['tasks']['water']['completion_latency_ms'] - sim['tasks']['water']['completion_latency_ms'])
            self.assertEqual(house, late['metrics']['whole_house_completion_ms'] - sim['metrics']['whole_house_completion_ms'])

    def test_appointment_distinct_from_physical_load_and_500ms_boundary(self):
        row = self.rows['F2R1-D-F2-01-competition-late|DeadlineAwareCoordinator']
        bg = row['arrival_background']
        self.assertEqual(2, bg['physical_units_crossing_L'])
        self.assertEqual(['laundry'], [x['task_id'] for x in bg['future_reservations_created_before_L']])
        self.assertFalse(bg['future_reservations_created_before_L'][0]['counts_as_physical_load_at_L'])
        row = self.rows['F2R1-D-F2-02-competition-late|GateRetryRule']
        self.assertEqual(500, row['tasks']['water']['tardiness_ms'])

    def test_K_and_interaction_and_limits(self):
        for g in self.e['four_cell_evidence']:
            if g['policy'] == 'IndependentMultiAgent':
                self.assertEqual(0.5, g['coverage'])
                self.assertIsNone(g['water_completion_latency']['effects']['interaction'])
            elif g['policy'] == 'DeadlineAwareCoordinator':
                self.assertEqual(0.25, g['timely_service']['effects']['interaction'])
        self.assertEqual(48, self.e['diagnostics_equal_count'])
        self.assertEqual(0, self.e['simulator_runs'])
        self.assertFalse(self.e['cross_family_analysis_created'])
        self.assertFalse(self.e['rankings_or_inferential_statistics_created'])

    def test_changed_reviewed_bytes_block_extraction(self):
        with patch.object(f, 'sha', return_value='bad'), self.assertRaises(AssertionError):
            f.extract()


if __name__ == '__main__':
    unittest.main()

