"""Read-only v2 statistics acceptance tests; no new performance simulations."""
import unittest
from homecoord_bench.tests import test_latency_window_pilot_v1 as v1
from homecoord_bench.task_revision import latency_window_statistics_v2 as exp
from homecoord_bench.task_revision import latency_window_crosscheck_v2 as cross


class SavedLatencyWindowV2Tests(v1.SavedLatencyWindowTests):
    def test_all_saved_event_audits_and_statistics_recount(self):
        for d in self.docs:
            self.assertEqual(d['pair'], exp.old.pair_audit(d['input'], d['runs']))
        self.assertEqual(self.stat, exp.build_statistics())

    def test_separate_arithmetic_does_not_run_simulator(self):
        outcome = cross.build()
        self.assertEqual(2, outcome['metadata_revision'])
        self.assertEqual(0, outcome['new_simulator_runs'])
        self.assertEqual(88, outcome['formal_runs'])
        self.assertGreater(outcome['top_level_checks'], 1000)


class MetadataCorrectionTests(unittest.TestCase):
    def test_explicit_grid_is_identical_to_original_plan(self):
        plan = exp.read(exp.PLAN)
        original = exp.base.read(exp.base.PLAN)
        self.assertEqual(original['configurations'], plan['configurations'])
        self.assertEqual(original['worlds'], plan['worlds'])
        self.assertEqual(plan, exp.corrected_plan())

    def test_nonzero_contrast_count_equals_slots_minus_baselines(self):
        plan = exp.read(exp.PLAN)
        count = len(plan['configurations'])-len(plan['worlds'])
        self.assertEqual(36, count)
        self.assertEqual(count, plan['scope']['delay_contrasts'])
        self.assertEqual(2*count, plan['scope']['delay_arm_contrasts'])

    def test_no_extra_performance_runs_for_correction(self):
        lock = exp.read(exp.LOCK2)
        self.assertEqual(0, lock['new_performance_runs'])
        self.assertTrue(lock['original_grid_and_predictions_unchanged'])
        self.assertEqual('author_post_execution_metadata_correction_not_new_preregistration', lock['status'])
        exp.verify_lock()

    def test_original_preflight_failure_is_retained(self):
        f = exp.read(exp.OUT+'/statistics_preflight_failure_v1.json')
        self.assertFalse(f['statistics_v1_written'])
        self.assertFalse(f['performance_grid_or_predictions_changed'])
        self.assertEqual(0, f['additional_performance_runs_required'])

    def test_old_meta_count_remains_original_not_rewritten(self):
        self.assertEqual(40, exp.base.read(exp.base.PLAN)['scope']['delay_contrasts'])
        self.assertEqual(36, exp.read(exp.PLAN)['scope']['delay_contrasts'])


if __name__ == '__main__':
    unittest.main()
