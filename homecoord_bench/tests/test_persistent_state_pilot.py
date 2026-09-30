import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from probe_persistent_state import run, simulate  # noqa: E402


class PersistentStatePilotTests(unittest.TestCase):
    def test_original_overlap_rule_misses_persistent_window_state(self):
        with TemporaryDirectory() as directory:
            result = run(Path(directory) / "pilot.json")
        self.assertTrue(result["legacy"]["process_valid_success"])
        self.assertEqual("open", result["legacy"]["window_state_at_cooling_start"])
        overlap = simulate(1600, 150, "ActionOverlapLock")
        state_gate = simulate(1600, 150, "StateGate")
        self.assertGreater(overlap["open_window_cooling_ms"], 0)
        self.assertEqual(0, state_gate["open_window_cooling_ms"])
        self.assertTrue(state_gate["valid_on_time"])

    def test_no_ventilation_control_has_no_coordination_penalty(self):
        starts = {policy: simulate(850, 150, policy)["cooling_start_ms"]
                  for policy in ("Independent", "ActionOverlapLock", "StateGate", "FullSequence")}
        self.assertEqual({800}, set(starts.values()))


if __name__ == "__main__":
    unittest.main()
