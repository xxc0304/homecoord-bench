"""Invariant checks for the normalized C3 resource-pressure batch."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_c3_normalized_capacity_batch import CONDITIONS, generate, make_condition
from runtime.dry_run import DryRunClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation


class C3NormalizedCapacityBatchTests(unittest.TestCase):
    def test_generation_preserves_a_single_changed_factor(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = generate(Path(directory))
        self.assertEqual(manifest["audit"]["status"], "pass")
        self.assertEqual(len(manifest["conditions"]), len(CONDITIONS))
        self.assertEqual(
            [item["load_to_capacity_ratio"] for item in manifest["conditions"][:3]],
            [0.8, 1.0, 1.2],
        )
        self.assertEqual(manifest["capacity_semantics"], "managed_shared_power_budget")

    def test_every_condition_is_executable_with_the_same_strong_baseline(self):
        for name, ratio in CONDITIONS:
            episode = make_condition(name, ratio)
            self.assertEqual(validate_event_episode(episode), [], episode["episode_id"])
            _, result = run_event_simulation(
                episode,
                DryRunClient(),
                "CapacityAwareDeadlineCoordinator",
                "normalized capacity test",
                shared_safety_gate=True,
            )
            self.assertTrue(result["process_valid_success"], episode["episode_id"])
            self.assertTrue(all(result["task_service"].values()), episode["episode_id"])


if __name__ == "__main__":
    unittest.main()
