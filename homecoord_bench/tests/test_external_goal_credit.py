"""Audit tests for goals satisfied without agent-produced actions."""

import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from audit_external_goal_credit import audit  # noqa: E402


class ExternalGoalCreditTests(unittest.TestCase):
    def test_audit_catches_c4_event_only_goal_success(self):
        report = audit()
        by_id = {
            record["episode_id"]: record
            for record in report["records"]
            if record["path"].startswith("data/candidates/")
        }

        self.assertEqual(20, len(by_id))
        self.assertFalse(by_id["HC-M16"]["environment_only_goal_success"])
        for episode_id in ("HC-M17", "HC-M18", "HC-M19", "HC-M20"):
            self.assertTrue(by_id[episode_id]["exogenous_event_prefix_satisfies_goals"])
        self.assertEqual(34, report["episode_count"])
        self.assertEqual(0, report["initial_state_goal_success_count"])
        self.assertEqual(4, report["event_only_goal_success_count"])
        self.assertEqual(0, report["error_count"])


if __name__ == "__main__":
    unittest.main()
