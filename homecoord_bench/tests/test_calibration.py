import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import load_json  # noqa: E402
from runtime.calibration import calibration_manifest, parameterize_episode  # noqa: E402


class CalibrationTests(unittest.TestCase):
    def test_sampling_is_deterministic_and_within_declared_ranges(self):
        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M13.json")
        first = parameterize_episode(episode, 3)
        second = parameterize_episode(episode, 3)
        self.assertEqual(first, second)
        for grounding in first["action_grounding"]:
            nominal = next(
                item for item in episode["action_grounding"]
                if item["task_id"] == grounding["task_id"]
            )
            self.assertGreaterEqual(grounding["duration_ms"], round(nominal["duration_ms"] * 0.80))
            self.assertLessEqual(grounding["duration_ms"], round(nominal["duration_ms"] * 1.20))

    def test_manifest_marks_synthetic_source(self):
        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M02.json")
        manifest = calibration_manifest(episode)
        self.assertEqual("synthetic_range", manifest["calibration_status"])
        self.assertEqual(2, len(manifest["actions"]))


if __name__ == "__main__":
    unittest.main()
