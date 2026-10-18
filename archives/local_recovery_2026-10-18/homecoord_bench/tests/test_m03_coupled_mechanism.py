"""Check that the M03 2x2 mechanism pilot is paired and executable."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_m03_coupled_mechanism import CAPACITY, ENERGY_RELEASE_MS, make_episode, run
from runtime.episode_validation import validate_event_episode


class M03CoupledMechanismTests(unittest.TestCase):
    def test_four_arms_change_only_two_declared_factors(self):
        arms = [make_episode(o, c) for o in ENERGY_RELEASE_MS for c in CAPACITY]
        self.assertEqual(4, len(arms))
        for episode in arms:
            self.assertEqual([], validate_event_episode(episode))
            self.assertEqual(3, len(episode["agents"]))
            self.assertEqual({"C1", "C3"}, {rule["type"] for rule in episode["conflict_rules"]})
            self.assertFalse(episode["calibration"]["physical_parameters_verified"])

        normalized = []
        for arm in arms:
            item = deepcopy(arm)
            item.pop("episode_id")
            item["variant"].pop("overlap")
            item["variant"].pop("capacity")
            item["home"]["resources"].pop("max_power_kw")
            item["conflict_rules"][-1].pop("capacity")
            item["parameter_provenance"].pop("managed_load_budget_kw")
            item["parameter_provenance"].pop("energy_task_release_at_ms")
            next(task for task in item["task_stream"] if task["task_id"] == "peak_off").pop("release_at_ms")
            normalized.append(item)
        self.assertTrue(all(item == normalized[0] for item in normalized[1:]))

    def test_strict_tool_contract_and_strong_baseline_are_not_artificially_broken(self):
        rows = run()["rows"]
        self.assertEqual(24, len(rows))
        self.assertFalse(any(
            "tool_not_authorized" in row["action_rejections"] for row in rows
        ))
        for row in rows:
            if row["policy"] in {
                "ConstraintCoordinator", "DeadlineAwareCoordinator",
                "CapacityAwareDeadlineCoordinator",
            }:
                self.assertTrue(row["process_valid_success"], row)
                self.assertTrue(all(row["task_service"].values()), row)
                self.assertTrue(row["all_deadlines_met"], row)


if __name__ == "__main__":
    unittest.main()
