"""Audit regression for the saved live parallel model pilot."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_c3_parallel_model_pilot import SOURCE, audit


class C3ParallelModelPilotAuditTests(unittest.TestCase):
    def test_saved_live_pilot_is_complete_and_blind(self):
        if not SOURCE.exists():
            self.skipTest("live parallel pilot has not been run")
        report = audit(output=None)
        self.assertEqual("pass", report["status"])
        self.assertEqual([1, 2, 3], report["repetitions"])
        self.assertEqual(6, report["batch_count"])
        self.assertEqual(21, report["model_call_record_count"])
        self.assertEqual(21, report["correct_single_action_proposal_count"])
        self.assertEqual(72, report["replay_count"])
        self.assertEqual(0, report["hidden_answer_leak_count"])


if __name__ == "__main__":
    unittest.main()
