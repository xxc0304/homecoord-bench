"""Checks the C4 phase placement and explicit stop/restart tradeoff."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluate import ROOT
from probe_c4_phase_recovery import event_times, recovery_contract, run


class C4PhaseRecoveryTests(unittest.TestCase):
    def test_phase_offsets_are_relative_to_one_proposal(self):
        latency = 1400
        start = latency + 100
        self.assertEqual(event_times(latency, "precommit")[0], start - 100)
        self.assertEqual(event_times(latency, "inflight")[0], start + 1500)
        self.assertEqual(event_times(latency, "postcomplete")[0], start + 4000)

    def test_stop_reduces_exposure_but_only_restart_serves_task(self):
        gate = recovery_contract(1400, "inflight", "GateOnly")
        stop = recovery_contract(1400, "inflight", "StopOnly")
        repair = recovery_contract(1400, "inflight", "StopAndRestart")
        self.assertEqual(gate["unsafe_overlap_duration_ms"], 1500)
        self.assertEqual(stop["unsafe_overlap_duration_ms"], 200)
        self.assertEqual(repair["unsafe_overlap_duration_ms"], 200)
        self.assertFalse(stop["task_served"])
        self.assertTrue(repair["task_served"])
        self.assertEqual(repair["task_completion_ms"] - gate["task_completion_ms"], 3600)

    def test_phase_replay_matches_core_gate_only_execution(self):
        source = ROOT / "results" / "c4_recorded_proposal_boundary_20260928.json"
        if not source.exists():
            self.skipTest("recorded C4 proposals are unavailable")
        report = run()
        self.assertEqual(len(report["core_rows"]), 80)
        self.assertEqual(len(report["recovery_rows"]), 60)
        for phase in ("no_event", "postcomplete"):
            independent = [row for row in report["core_rows"]
                           if row["phase"] == phase and
                           row["policy"] == "IndependentMultiAgent"]
            self.assertTrue(all(row["process_valid_success"] for row in independent))
        source_payload = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(len(source_payload["rows"]), 5)


if __name__ == "__main__":
    unittest.main()
