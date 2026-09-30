"""Checks for normalized C3 replay using saved model proposals."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_normalized_capacity import SOURCE, run


class C3NormalizedCapacityReplayTests(unittest.TestCase):
    def test_saved_proposals_cover_all_pressure_policy_pairs(self):
        if not SOURCE.exists():
            self.skipTest("saved three-load proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(report["api_calls"], 0)
        self.assertEqual(len(report["rows"]), report["saved_proposal_groups"] * 4 * 5)
        for condition in report["summary"].values():
            self.assertEqual(len(condition["by_policy"]), 5)


if __name__ == "__main__":
    unittest.main()
