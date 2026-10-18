"""Validate event-triggered task release and its coordination consequence."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_m02_dependency_capacity import make_episode, run
from runtime.dry_run import DryRunClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation


class M02DependencyCapacityTests(unittest.TestCase):
    def test_dryer_is_released_at_real_washer_completion(self):
        rows = run()["rows"]
        self.assertEqual(24, len(rows))
        for row in rows:
            releases = {item["task_id"]: item for item in row["task_releases"]}
            wash_done = next(
                item["timestamp_ms"] for item in row["action_completions"]
                if item["task_id"] == "wash_laundry"
            )
            self.assertEqual(wash_done, releases["dry_laundry"]["timestamp_ms"])
            self.assertEqual("wash_laundry", releases["dry_laundry"]["trigger_task_id"])

    def test_failed_predecessor_does_not_release_child_and_cycle_is_invalid(self):
        episode = make_episode("tight")
        episode["home"]["resources"]["max_power_kw"] = 0.5
        episode["conflict_rules"][0]["capacity"] = 0.5
        trace, _ = run_event_simulation(
            deepcopy(episode), DryRunClient(), "ConstraintCoordinator", "",
            shared_safety_gate=True,
        )
        released = {
            item["task_id"] for item in trace["events"]
            if item["type"] == "task_released"
        }
        self.assertNotIn("dry_laundry", released)

        cyclic = make_episode("tight")
        next(item for item in cyclic["task_stream"]
             if item["task_id"] == "wash_laundry")["release_after_task_completion"] = "dry_laundry"
        self.assertTrue(any("cycle" in error for error in validate_event_episode(cyclic)))

    def test_selective_waiting_is_useful_only_in_frozen_synthetic_condition(self):
        rows = run()["rows"]
        selected = {
            (row["capacity_condition"], row["latency_condition"], row["policy"]): row
            for row in rows
        }
        tight_late = selected[("tight", "late_water", "CapacityAwareDeadlineCoordinator")]
        self.assertTrue(tight_late["all_deadlines_met"])
        self.assertTrue(all(tight_late["task_service"].values()))
        self.assertFalse(selected[("tight", "late_water", "ConstraintCoordinator")]["all_deadlines_met"])
        self.assertFalse(selected[("loose", "late_water", "DeadlineAwareCoordinator")]["all_deadlines_met"])
        self.assertTrue(selected[("loose", "late_water", "ConstraintCoordinator")]["all_deadlines_met"])


if __name__ == "__main__":
    unittest.main()
