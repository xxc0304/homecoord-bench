"""Checks for the independent C3 task-structure replication."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_non_nested_templates import TEMPLATES, run


class C3NonNestedTemplateTests(unittest.TestCase):
    def test_templates_have_disjoint_devices_and_agents(self):
        left, right = TEMPLATES.values()
        self.assertTrue({task.device for task in left}.isdisjoint(task.device for task in right))
        self.assertEqual(len(left), len({task.agent_id for task in left}))
        self.assertEqual(len(right), len({task.agent_id for task in right}))

    def test_factorial_counts_and_no_api(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run(Path(directory) / "result.json")
        self.assertEqual(0, report["api_calls"])
        # (3! + 4!) orders x 4 pressures x 4 policies.
        self.assertEqual((6 + 24) * 4 * 4, len(report["rows"]))
        self.assertEqual(6, report["templates"]["KITCHEN_CIRCUIT"]["arrival_orders"])
        self.assertEqual(24, report["templates"]["MORNING_DEPARTURE"]["arrival_orders"])
        for template in report["summary"].values():
            # The tasks are feasible under every declared pressure when all
            # released proposals are collected and scheduled by deadline.
            for pressure in template.values():
                wait_all = pressure["DeadlineAwareCoordinator"]
                self.assertEqual(wait_all["orders"], wait_all["all_deadlines_met"])
        morning_high = report["summary"]["MORNING_DEPARTURE"]["1.6"]
        self.assertLess(
            morning_high["CapacityAwareDeadlineCoordinator"]["all_deadlines_met"],
            morning_high["CapacityAwareDeadlineCoordinator"]["orders"],
        )


if __name__ == "__main__":
    unittest.main()
