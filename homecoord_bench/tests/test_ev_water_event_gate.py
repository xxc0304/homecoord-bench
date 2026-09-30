"""C3 timing contrast under a common safety gate and completion semantics."""

import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from probe_ev_water_event_gate import RecordedLatencyScriptedActions  # noqa: E402
from probe_physical_capacity_v2 import make_episode  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402


class EvWaterEventGateTests(unittest.TestCase):
    def run_case(self, condition, policy):
        # The measured latency ordering from source repetition 1 makes the
        # lower-priority water proposal return before the EV proposal.
        latencies = {"charge_ev": 1424, "heat_water": 1144}
        episode = make_episode(condition)
        episode["home"]["resources"]["task_power_bounds_kw"] = {
            "charge_ev": 4.0, "heat_water": 3.0,
        }
        return run_event_simulation(
            episode, RecordedLatencyScriptedActions(latencies),
            policy, "", shared_safety_gate=True,
        )

    def test_low_capacity_urgent_task_needs_ordering_not_just_veto(self):
        _, no_advance = self.run_case("conflict", "IndependentMultiAgent")
        _, fifo = self.run_case("conflict", "ConstraintCoordinator")
        _, deadline = self.run_case("conflict", "DeadlineAwareCoordinator")
        _, capacity_aware = self.run_case("conflict", "CapacityAwareDeadlineCoordinator")
        self.assertEqual(1, no_advance["shared_safety_gate_rejection_count"])
        self.assertEqual(0, sum(no_advance["conflict_counts"].values()))
        self.assertFalse(no_advance["task_service"]["charge_ev"])
        self.assertTrue(all(fifo["task_service"].values()))
        self.assertFalse(fifo["task_deadline_met"]["charge_ev"])
        self.assertTrue(deadline["all_deadlines_met"])
        self.assertTrue(capacity_aware["all_deadlines_met"])
        self.assertEqual(0, deadline["shared_safety_gate_rejection_count"])

    def test_high_capacity_waits_unnecessarily_for_second_proposal(self):
        _, immediate = self.run_case("control", "ConstraintCoordinator")
        _, wait_all = self.run_case("control", "DeadlineAwareCoordinator")
        _, capacity_aware = self.run_case("control", "CapacityAwareDeadlineCoordinator")
        self.assertTrue(immediate["all_deadlines_met"])
        self.assertTrue(wait_all["all_deadlines_met"])
        self.assertEqual(180, wait_all["first_action_start_latency_ms"] -
                         immediate["first_action_start_latency_ms"])
        self.assertEqual(immediate["first_action_start_latency_ms"],
                         capacity_aware["first_action_start_latency_ms"])
        self.assertTrue(capacity_aware["all_deadlines_met"])

    def test_missing_power_bounds_fall_back_to_waiting(self):
        episode = make_episode("conflict")
        _, result = run_event_simulation(
            episode, RecordedLatencyScriptedActions({
                "charge_ev": 1424, "heat_water": 1144,
            }), "CapacityAwareDeadlineCoordinator", "", shared_safety_gate=True,
        )
        self.assertTrue(result["all_deadlines_met"])

    def test_understated_power_bound_loses_timeliness_but_not_safety(self):
        episode = make_episode("conflict")
        episode["home"]["resources"]["task_power_bounds_kw"] = {
            "charge_ev": 2.0, "heat_water": 3.0,
        }
        _, result = run_event_simulation(
            episode, RecordedLatencyScriptedActions({
                "charge_ev": 1424, "heat_water": 1144,
            }), "CapacityAwareDeadlineCoordinator", "", shared_safety_gate=True,
        )
        self.assertFalse(result["task_deadline_met"]["charge_ev"])
        self.assertEqual(0, sum(result["conflict_counts"].values()))
        self.assertEqual(0, result["shared_safety_gate_rejection_count"])

    def test_invalid_public_power_bound_is_rejected(self):
        episode = make_episode("conflict")
        episode["home"]["resources"]["task_power_bounds_kw"] = {"charge_ev": -1.0}
        with self.assertRaisesRegex(ValueError, "task_power_bounds_kw"):
            run_event_simulation(
                episode, RecordedLatencyScriptedActions({
                    "charge_ev": 1424, "heat_water": 1144,
                }), "CapacityAwareDeadlineCoordinator", "", shared_safety_gate=True,
            )


if __name__ == "__main__":
    unittest.main()
