"""Regression checks for the C3 scale and arrival-order probe."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_structural_generalization import make_episode, run


class C3StructuralGeneralizationTests(unittest.TestCase):
    def test_episode_has_distinct_roles_and_declared_pressure(self):
        for count in (2, 3, 5):
            episode = make_episode(count, 1.2)
            self.assertEqual(count, len(episode["agents"]))
            self.assertEqual(count, len({agent["agent_id"] for agent in episode["agents"]}))
            resources = episode["home"]["resources"]
            total = sum(resources["task_power_bounds_kw"].values())
            self.assertAlmostEqual(1.2, total / resources["max_power_kw"], places=5)

    def test_full_factorial_cell_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run(Path(directory) / "result.json")
        self.assertEqual(0, report["api_calls"])
        # (2! + 3! + 5!) orders x 4 pressures x 4 policies.
        self.assertEqual((2 + 6 + 120) * 4 * 4, len(report["rows"]))
        for count, orders in ((2, 2), (3, 6), (5, 120)):
            for pressure in ("0.8", "1", "1.2", "1.6"):
                for cell in report["summary"][str(count)][pressure].values():
                    self.assertEqual(orders, cell["orders"])


if __name__ == "__main__":
    unittest.main()
