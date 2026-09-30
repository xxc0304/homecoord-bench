"""Contract and scoring tests for incoming physical trajectories."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_hc_m06_physical_trace_fixture import make_trace  # noqa: E402
from runtime.physical_trace import score_trace, validate_matched_pair, validate_trace  # noqa: E402
from score_physical_traces import audit_bundle  # noqa: E402


class PhysicalTraceTests(unittest.TestCase):
    def test_trace_metrics_come_from_samples_and_keep_provenance(self):
        trace, source = make_trace("conflict", "Independent")
        self.assertEqual([], validate_trace(trace))
        score = score_trace(trace)
        self.assertEqual("synthetic_fixture", score["source_kind"])
        self.assertEqual(source["goal_completion_ms"], score["observed_goal_completion_ms"])
        self.assertAlmostEqual(source["heater_energy_wh"], score["heater_energy_wh"], places=4)
        self.assertEqual(score["heater_energy_wh"], score["heater_energy_by_deadline_wh"])
        self.assertEqual([344000, 345000], score["goal_completion_observation_interval_ms"])
        self.assertEqual(1000, score["max_sample_gap_ms"])

    def test_pair_requires_only_declared_co2_change(self):
        conflict, _ = make_trace("conflict", "StateGate")
        control, _ = make_trace("control", "StateGate")
        self.assertEqual([], validate_matched_pair(conflict, control))
        changed = copy.deepcopy(control)
        changed["trial"]["initial_temp_c"] = 18.0
        changed["samples"][0]["indoor_temp_c"] = 18.0
        self.assertTrue(any("initial_temp_c" in e for e in validate_matched_pair(conflict, changed)))

    def test_malformed_samples_and_missing_provenance_are_rejected(self):
        trace, _ = make_trace("conflict", "Independent")
        broken = copy.deepcopy(trace)
        broken["source"]["calibration_status"] = ""
        broken["samples"][1]["t_ms"] = 0
        errors = validate_trace(broken)
        self.assertTrue(any("calibration_status" in e for e in errors))
        self.assertTrue(any("strictly increase" in e for e in errors))

    def test_sparse_sampling_reports_timing_uncertainty(self):
        trace, _ = make_trace("conflict", "Independent")
        trace["samples"] = trace["samples"][::10]
        score = score_trace(trace)
        self.assertTrue(score["time_resolution_warning"])
        self.assertGreater(score["max_sample_gap_ms"], 5000)
        self.assertLessEqual(score["goal_completion_observation_interval_ms"][0], 345000)
        self.assertGreaterEqual(score["goal_completion_observation_interval_ms"][1], 345000)

    def test_import_audit_requires_unique_matched_arms(self):
        conflict, _ = make_trace("conflict", "Independent")
        control, _ = make_trace("control", "Independent")
        audit = audit_bundle({"traces": [conflict, control]})
        self.assertEqual({"synthetic_fixture": 2}, audit["source_counts"])
        self.assertEqual(1, audit["matched_pairs_valid"])
        self.assertEqual(0, audit["time_resolution_warnings"])
        with self.assertRaisesRegex(ValueError, "duplicate trace_id"):
            audit_bundle({"traces": [conflict, control, conflict]})
        with self.assertRaisesRegex(ValueError, "missing matched"):
            audit_bundle({"traces": [conflict]})

    def test_truncated_trace_cannot_hide_deadline_failure_or_extrapolate_energy(self):
        failed, _ = make_trace("conflict", "StateGate")
        failed["samples"] = [sample for sample in failed["samples"] if sample["t_ms"] <= 200000]
        self.assertTrue(any("ends before deadline" in e for e in validate_trace(failed)))

        succeeded, _ = make_trace("conflict", "Independent")
        succeeded["samples"] = [sample for sample in succeeded["samples"] if sample["t_ms"] <= 345000]
        score = score_trace(succeeded)
        self.assertTrue(score["sampled_deadline_met"])
        self.assertIsNone(score["heater_energy_by_deadline_wh"])


if __name__ == "__main__":
    unittest.main()
