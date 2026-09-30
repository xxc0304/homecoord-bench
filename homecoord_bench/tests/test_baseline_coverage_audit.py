"""Guard against overstating policy coverage in the current pilot results."""

import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from audit_baseline_coverage import audit  # noqa: E402


class BaselineCoverageAuditTests(unittest.TestCase):
    def test_matrix_and_recorded_proposal_coverage_are_separated(self):
        report = audit()
        matrix = report["event_matrix"]
        replay = report["recorded_model_proposal_replay"]

        self.assertEqual(170, matrix["run_count"])
        self.assertEqual(34, matrix["episode_count"])
        self.assertIn("CentralSingleAgent", matrix["policies"])
        self.assertNotIn("CentralSingleAgent", replay["policies"])
        self.assertTrue(replay["central_agent_excluded"])
        self.assertTrue(replay["central_agent_exclusion_reason"])

    def test_deadline_and_online_rule_baselines_are_not_mislabeled_as_new_method(self):
        report = audit()
        deadline = report["deadline_sensitivity_replay"]
        online = report["direct_online_rule_replay"]

        self.assertEqual(200, deadline["run_count"])
        self.assertEqual(5, len(deadline["distinct_deadline_values_ms"]))
        self.assertEqual(40, online["run_count"])
        self.assertIn("WaitReleasedEDF", online["policies"])
        self.assertEqual("not_measured_in_current_event_matrix",
                         report["coordination_overhead"]["status"])


if __name__ == "__main__":
    unittest.main()
