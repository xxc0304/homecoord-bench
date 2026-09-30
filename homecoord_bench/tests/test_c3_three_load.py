"""Three-way C3 scheduling and shared-gate fairness checks."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluate import ROOT
from probe_c3_three_load import ScriptedProposalClient, make_episode
from probe_c3_three_load_model import replay_records
from runtime.event_simulator import run_event_simulation


LATENCIES = {"cook_dinner": 1800, "dry_laundry": 1200, "wash_dishes": 1000}


class ThreeLoadC3Tests(unittest.TestCase):
    def run_case(self, condition: str, policy: str):
        return run_event_simulation(
            make_episode(condition), ScriptedProposalClient(LATENCIES),
            policy, "", shared_safety_gate=True,
        )

    def test_three_task_low_capacity_requires_order_not_only_veto(self):
        _, independent = self.run_case("conflict", "IndependentMultiAgent")
        _, fifo = self.run_case("conflict", "ConstraintCoordinator")
        _, deadline = self.run_case("conflict", "DeadlineAwareCoordinator")
        _, capacity_aware = self.run_case("conflict", "CapacityAwareDeadlineCoordinator")
        self.assertGreater(independent["shared_safety_gate_rejection_count"], 0)
        self.assertFalse(all(independent["task_service"].values()))
        self.assertTrue(all(fifo["task_service"].values()))
        self.assertFalse(fifo["all_deadlines_met"])
        self.assertTrue(deadline["all_deadlines_met"])
        self.assertTrue(capacity_aware["all_deadlines_met"])
        self.assertEqual(0, sum(capacity_aware["conflict_counts"].values()))

    def test_pending_earlier_proposal_is_not_ignored(self):
        # After dryer returns, it remains held for the unseen dinner proposal.
        # Dishwasher is also held because its combined bound with that pending
        # dryer and dinner exceeds capacity. This caught a prior two-task-only
        # assumption in CapacityAwareDeadlineCoordinator.
        trace, result = self.run_case("conflict", "CapacityAwareDeadlineCoordinator")
        starts = [event["task_id"] for event in trace["events"]
                  if event["type"] == "action_started"]
        self.assertEqual(starts, ["cook_dinner", "dry_laundry", "wash_dishes"])
        self.assertTrue(result["all_deadlines_met"])

    def test_high_capacity_avoids_unneeded_wait(self):
        _, immediate = self.run_case("control", "IndependentMultiAgent")
        _, wait_all = self.run_case("control", "DeadlineAwareCoordinator")
        _, aware = self.run_case("control", "CapacityAwareDeadlineCoordinator")
        self.assertTrue(all(row["all_deadlines_met"] for row in (immediate, wait_all, aware)))
        self.assertEqual(aware["first_action_start_latency_ms"],
                         immediate["first_action_start_latency_ms"])
        self.assertGreater(wait_all["first_action_start_latency_ms"],
                           immediate["first_action_start_latency_ms"])

    def test_recorded_model_proposals_pair_capacity_conditions(self):
        source = ROOT / "results" / "c3_three_load_model_pilot_20260928.json"
        if not source.exists():
            self.skipTest("model proposal pilot has not been run")
        records = json.loads(source.read_text(encoding="utf-8"))["rows"][0]["model_records"]
        rows = replay_records(records, 1)
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({json.dumps(row["model_latency_by_task_ms"], sort_keys=True)
                              for row in rows}), 1)
        self.assertTrue(all(row["all_deadlines_met"] for row in rows
                            if row["policy"] == "CapacityAwareDeadlineCoordinator"))


if __name__ == "__main__":
    unittest.main()
