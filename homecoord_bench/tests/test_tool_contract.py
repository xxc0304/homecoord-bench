"""Strict-v1 draft actions must match visible tools and actual capabilities."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from make_representative_revision_drafts import make_drafts  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402
from runtime.protocol import build_agent_request  # noqa: E402
from runtime.tool_contract import validate_tool_call  # noqa: E402


class SpoofTargetClient(DryRunClient):
    def decide(self, request, instructions=""):
        decision = super().decide(request, instructions)
        if request["task"]["task_id"] == "comfort_cool":
            decision["actions"][0]["target"] = "bedroom_hvac"
        return decision


class ToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drafts = {e["episode_id"]: e for e in make_drafts()}

    def proposal(self, episode_id, task_id):
        episode = self.drafts[episode_id]
        task = next(t for t in episode["task_stream"] if t["task_id"] == task_id)
        agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
        request = build_agent_request(
            episode, agent, task, architecture="IndependentMultiAgent",
            current_time_ms=task["release_at_ms"], include_evaluation_hints=True,
            request_id="tool-contract-test",
        )
        action = DryRunClient().decide(request)["actions"][0]
        return episode, task, action

    def test_every_draft_template_is_authorized(self):
        for episode in self.drafts.values():
            for task in episode["task_stream"]:
                _, _, action = self.proposal(episode["episode_id"], task["task_id"])
                self.assertIsNone(validate_tool_call(episode, task["agent_id"], task["task_id"], action))

    def test_rejects_wrong_target_and_ungrounded_action(self):
        episode, task, action = self.proposal("HC-PAIR-C1-HVAC-CONFLICT", "comfort_cool")
        wrong = deepcopy(action)
        wrong["target"] = "bedroom_hvac"
        self.assertEqual("tool_not_authorized", validate_tool_call(episode, task["agent_id"], task["task_id"], wrong))
        altered = deepcopy(episode)
        altered["action_grounding"][0]["target"] = "other_hvac"
        self.assertEqual("ungrounded_tool_action", validate_tool_call(altered, task["agent_id"], task["task_id"], action))

    def test_rejects_out_of_range_and_missing_guard(self):
        episode, task, action = self.proposal("HC-PAIR-C3-HOME-POWER-OVER-CAPACITY", "study_light")
        action["parameters"][0]["value"] = 1000
        self.assertEqual("invalid_tool_parameters", validate_tool_call(episode, task["agent_id"], task["task_id"], action))
        episode, task, action = self.proposal("HC-PAIR-C4-CLEAN-INFLIGHT", "bedroom_clean")
        action["requires"] = []
        self.assertEqual("missing_tool_precondition", validate_tool_call(episode, task["agent_id"], task["task_id"], action))

    def test_runtime_rejects_spoofed_target_without_physical_action(self):
        episode = self.drafts["HC-PAIR-C1-HVAC-CONFLICT"]
        trace, _ = run_event_simulation(episode, SpoofTargetClient(), "IndependentMultiAgent", "")
        self.assertTrue(any(e["type"] == "action_rejected" and e["reason"] == "tool_not_authorized"
                            and e["task_id"] == "comfort_cool" for e in trace["events"]))
        self.assertFalse(any(e["type"] == "action_started" and e["task_id"] == "comfort_cool"
                             for e in trace["events"]))


if __name__ == "__main__":
    unittest.main()
