"""Tests for true-parallel proposal recording and deterministic replay."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import replay, sample_parallel
from probe_c3_structural_generalization import make_episode_from_specs


class FakeClient:
    def decide(self, request, instructions=""):
        action = request["available_actions"][0]
        return {
            "response_type": "action_proposal",
            "actions": [{
                "proposal_id": f"p-{request['task']['task_id']}",
                "target": action["target"],
                "operation": action["operation"],
                "parameters": [],
                "based_on_state_version": request["state_version"],
                "requires": [],
                "estimated_duration_ms": None,
                "estimated_power_kw": None,
            }],
            "accepted_proposal_ids": [],
            "rejected_proposal_ids": [],
            "defer_until_ms": None,
            "reason_code": "goal_progress",
        }


class C3ParallelModelPilotTests(unittest.TestCase):
    def test_parallel_sample_covers_every_task_without_answer_leakage(self):
        specs = TEMPLATES["KITCHEN_CIRCUIT"]
        episode = make_episode_from_specs("KITCHEN_CIRCUIT", specs, 1.2)
        sample = sample_parallel(FakeClient(), episode, 1)
        self.assertEqual(set(sample["records"]), {task.task_id for task in specs})
        self.assertEqual({}, sample["errors"])
        for record in sample["records"].values():
            self.assertNotIn("required_action", record["request"]["task"])
            self.assertNotIn("action_template", record["request"]["task"])
            self.assertGreater(record["logical_latency_ms"], 0)

    def test_recorded_batch_replays_all_pressure_policy_cells(self):
        specs = TEMPLATES["KITCHEN_CIRCUIT"]
        episode = make_episode_from_specs("KITCHEN_CIRCUIT", specs, 1.2)
        sample = sample_parallel(FakeClient(), episode, 1)
        rows = replay("KITCHEN_CIRCUIT", sample["records"], 1)
        self.assertEqual(3 * 4, len(rows))


if __name__ == "__main__":
    unittest.main()
