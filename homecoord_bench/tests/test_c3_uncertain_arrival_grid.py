"""Varied-arrival grid should preserve pairing and avoid impossible examples."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_uncertain_arrival_grid import (
    ARRIVALS_S, DEV_ARRIVALS_S, HELD_OUT_ARRIVALS_S, HOLD_WINDOWS_S,
    SOURCE, make_arrival_case, run,
)
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_structural_generalization import make_episode_from_specs


class C3UncertainArrivalGridTests(unittest.TestCase):
    def test_arrival_splits_and_pair_isolation(self):
        self.assertEqual(set(ARRIVALS_S), set(DEV_ARRIVALS_S) | set(HELD_OUT_ARRIVALS_S))
        self.assertFalse(set(DEV_ARRIVALS_S) & set(HELD_OUT_ARRIVALS_S))
        base = make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.6)
        cases = [make_arrival_case(base, seconds) for seconds in ARRIVALS_S]
        for a, b in zip(cases, cases[1:]):
            self.assertEqual(a["home"]["resources"], b["home"]["resources"])
            for left, right in zip(a["task_stream"], b["task_stream"]):
                changes = {key for key in left if left[key] != right[key]}
                self.assertTrue(changes <= {"release_at_ms"})
        self.assertNotIn(60, HOLD_WINDOWS_S)

    def test_all_cells_are_feasible_and_same_saved_batches(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(756, len(report["rows"]))
        self.assertTrue(all(row["ideal_feasible"] for row in report["rows"]))
        self.assertEqual({1, 2, 3}, {row["repetition"] for row in report["rows"]})
        for pressure in ("0.8", "1.2", "1.6"):
            for hold in HOLD_WINDOWS_S:
                summary = report["summary"][pressure][str(hold)]
                self.assertEqual(6, summary["no_event"]["runs"])
                self.assertEqual(18, summary["development"]["event_runs"])
                self.assertEqual(18, summary["held_out_times"]["event_runs"])


if __name__ == "__main__":
    unittest.main()
