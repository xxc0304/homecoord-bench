"""Check power-envelope sensitivity against saved live proposal replay."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_power_envelope_sensitivity import SOURCE, run


class C3PowerEnvelopeSensitivityTests(unittest.TestCase):
    def test_factor_one_matches_original_live_replay(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(432, len(report["rows"]))
        original = json.loads(SOURCE.read_text(encoding="utf-8"))
        lookup = {
            (row["template_id"], row["repetition"], row["pressure"], row["policy"]): row
            for row in original["replays"]
        }
        for row in report["rows"]:
            if row["load_factor"] == 1.0:
                peer = lookup[(row["template_id"], row["repetition"],
                               row["nominal_pressure"], row["policy"])]
                self.assertEqual(row["all_deadlines_met"], peer["all_deadlines_met"])
                self.assertEqual(row["first_action_start_latency_ms"],
                                 peer["first_action_start_latency_ms"])


if __name__ == "__main__":
    unittest.main()
