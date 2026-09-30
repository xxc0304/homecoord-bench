"""Check lower-bound deadline feasibility on the current physical pilot pair."""

import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from audit_deadline_feasibility import audit  # noqa: E402
from probe_physical_capacity_v2 import make_episode  # noqa: E402


class DeadlineFeasibilityAuditTests(unittest.TestCase):
    def test_current_conflict_and_control_have_expected_feasible_order_sets(self):
        report = audit(BENCH_ROOT / "data")
        rows = {row["episode_id"]: row for row in report["rows"]}
        conflict = rows["HC-PHYSICAL-V2-EV-WATER-CONFLICT"]
        control = rows["HC-PHYSICAL-V2-EV-WATER-CONTROL"]

        self.assertEqual(4, report["deadline_task_count"])
        self.assertEqual("order_sensitive", conflict["status"])
        self.assertEqual([["charge_ev", "heat_water"]], conflict["feasible_dispatch_orders"])
        self.assertEqual("feasible_all_capacity_orders", control["status"])
        self.assertEqual(2, control["deadline_feasible_order_count"])
        self.assertEqual("assumed_or_unverified", conflict["workload_status"])

    def test_impossibly_short_deadline_is_not_called_schedulable(self):
        episode = make_episode("control")
        episode["task_stream"][0]["completion_deadline_ms"] = 1_000
        from audit_deadline_feasibility import audit_episode

        result = audit_episode(episode, "synthetic-test.json")
        self.assertEqual("infeasible_under_declared_workload", result["status"])
        self.assertEqual([], result["feasible_dispatch_orders"])


if __name__ == "__main__":
    unittest.main()
