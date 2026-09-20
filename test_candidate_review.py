import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import load_json  # noqa: E402
from review_candidates import audit_episode  # noqa: E402


class CandidateReviewTests(unittest.TestCase):
    def test_all_implemented_candidates_pass_machine_pre_review(self):
        paths = sorted((BENCH_ROOT / "data" / "candidates").glob("*.json"))
        self.assertEqual(20, len(paths))
        for path in paths:
            with self.subTest(episode=path.stem):
                result = audit_episode(load_json(path))
                self.assertTrue(result["pre_review_pass"])
                self.assertEqual("synthetic_range", result["calibration_status"])


if __name__ == "__main__":
    unittest.main()
