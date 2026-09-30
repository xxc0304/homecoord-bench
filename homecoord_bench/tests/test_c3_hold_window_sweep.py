"""Check fixed-hold threshold against event order and paired no-event cost."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_hold_window_sweep import SOURCE, run


class C3HoldWindowSweepTests(unittest.TestCase):
    def test_event_release_precedes_equal_time_hold_expiry(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(252, len(report["rows"]))
        present = report["summary"]["1.6"]["present"]
        self.assertEqual(0, present["59000"]["all_deadlines_met"])
        self.assertEqual(6, present["60000"]["all_deadlines_met"])
        absent = report["summary"]["1.6"]["absent"]
        self.assertEqual(6, absent["59000"]["all_deadlines_met"])
        self.assertEqual(6, absent["60000"]["all_deadlines_met"])
        self.assertGreater(absent["60000"]["median_first_action_start_latency_ms"],
                           absent["0"]["median_first_action_start_latency_ms"])


if __name__ == "__main__":
    unittest.main()
