"""Safety-floor comparisons must not rely on unsafe independent execution."""

import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from make_representative_revision_drafts import make_drafts  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402


class SharedSafetyGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episodes = {item["episode_id"]: item for item in make_drafts()}

    def test_c1_independent_is_vetoed_and_constraint_preserves_service(self):
        episode = self.episodes["HC-PAIR-C1-HVAC-CONFLICT"]
        trace, independent = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", "",
            shared_safety_gate=True,
        )
        _, coordinated = run_event_simulation(
            episode, DryRunClient(), "ConstraintCoordinator", "",
            shared_safety_gate=True,
        )
        self.assertEqual(0, sum(independent["conflict_counts"].values()))
        self.assertEqual(1, independent["shared_safety_gate_rejection_count"])
        self.assertTrue(any(event.get("reason") == "shared_gate_action_conflict"
                            for event in trace["events"]))
        self.assertFalse(all(independent["task_service"].values()))
        self.assertTrue(all(coordinated["task_service"].values()))
        # A final-state goal can pass even though another Agent's service was
        # vetoed; the benchmark must keep these outcomes separate.
        self.assertTrue(independent["final_goal_success"])
        self.assertIsNone(independent["task_action_finish_time_ms"]["peak_off"])
        self.assertTrue(all(value is not None for value in
                            coordinated["task_action_finish_time_ms"].values()))
        self.assertGreater(max(coordinated["task_action_finish_time_ms"].values()),
                           coordinated["task_completion_time_ms"])

    def test_c3_device_lock_is_not_a_capacity_baseline(self):
        episode = self.episodes["HC-PAIR-C3-HOME-POWER-OVER-CAPACITY"]
        _, device_lock = run_event_simulation(
            episode, DryRunClient(), "RuleCoordinator", "",
            shared_safety_gate=True,
        )
        _, constraint = run_event_simulation(
            episode, DryRunClient(), "ConstraintCoordinator", "",
            shared_safety_gate=True,
        )
        self.assertEqual(0, sum(device_lock["conflict_counts"].values()))
        self.assertEqual(1, device_lock["shared_safety_gate_rejection_count"])
        self.assertFalse(all(device_lock["task_service"].values()))
        self.assertTrue(all(constraint["task_service"].values()))

    def test_safe_control_has_no_gate_rejection(self):
        episode = self.episodes["HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL"]
        _, independent = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", "",
            shared_safety_gate=True,
        )
        self.assertEqual(0, independent["shared_safety_gate_rejection_count"])
        self.assertTrue(all(independent["task_service"].values()))


if __name__ == "__main__":
    unittest.main()
