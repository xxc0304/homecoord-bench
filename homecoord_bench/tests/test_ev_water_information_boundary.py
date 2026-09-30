"""Check the paired information-boundary pilot's key interpretation."""

import sys
import tempfile
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from probe_ev_water_information_boundary import run_pilot  # noqa: E402


class EvWaterInformationBoundaryTests(unittest.TestCase):
    def test_bound_errors_change_timeliness_or_wait_not_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_pilot(Path(tmp) / "pilot.json")
        self.assertEqual(180, len(report["rows"]))
        self.assertEqual(0, report["new_api_calls"])
        self.assertFalse(report["actual_rule_wall_clock_measured"])
        self.assertTrue(all(row["conflict_count"] == 0 for row in report["rows"]))
        self.assertTrue(all(row["all_tasks_served"] for row in report["rows"]))

        def select(condition, profile):
            return next(row for row in report["rows"]
                        if row["source_repetition"] == 1
                        and row["condition"] == condition
                        and row["policy"] == "CapacityAwareDeadlineCoordinator"
                        and row["bound_profile"] == profile
                        and row["synthetic_coordination_delay_ms"] == 0)

        low_accurate = select("conflict", "accurate")
        low_under = select("conflict", "ev_understated")
        high_accurate = select("control", "accurate")
        high_over = select("control", "ev_overstated")
        self.assertTrue(low_accurate["all_deadlines_met"])
        self.assertFalse(low_under["task_deadline_met"]["charge_ev"])
        self.assertEqual(0, low_under["shared_safety_gate_rejection_count"])
        self.assertEqual(180, high_over["first_action_start_latency_ms"] -
                         high_accurate["first_action_start_latency_ms"])


if __name__ == "__main__":
    unittest.main()
