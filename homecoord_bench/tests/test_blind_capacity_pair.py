import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from probe_blind_capacity_pair_20260926 import make_episode  # noqa: E402
from run_protocol_pilot import INSTRUCTIONS  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.execution import run_closed_loop_episode  # noqa: E402
from runtime.protocol import build_agent_request  # noqa: E402


class BlindCapacityPairTests(unittest.TestCase):
    def test_live_request_has_choice_without_answer_key(self):
        episode = make_episode(1.2)
        agent, task = episode["agents"][0], episode["task_stream"][0]
        request = build_agent_request(episode, agent, task,
                                      architecture="IndependentMultiAgent", current_time_ms=0)
        self.assertNotIn("required_action", request["task"])
        self.assertNotIn("action_template", request["task"])
        self.assertEqual(2, len(request["available_actions"]))
        self.assertEqual({"set_reading", "off"},
                         {action["operation"] for action in request["available_actions"]})

    def test_capacity_toggle_changes_only_conflict_and_waiting(self):
        low, high = make_episode(1.2), make_episode(1.6)
        self.assertEqual(low["task_stream"], high["task_stream"])
        self.assertEqual(low["tool_catalog"], high["tool_catalog"])
        results = {}
        for label, episode in (("low", low), ("high", high)):
            for architecture in ("IndependentMultiAgent", "ConstraintCoordinator"):
                _, result = run_closed_loop_episode(
                    episode, DryRunClient(), architecture, INSTRUCTIONS, synthetic_latency=True
                )
                results[(label, architecture)] = result
        self.assertEqual(1, results[("low", "IndependentMultiAgent")]["conflict_counts"]["C3"])
        self.assertEqual(0, results[("low", "ConstraintCoordinator")]["conflict_counts"]["C3"])
        self.assertGreater(results[("low", "ConstraintCoordinator")]["task_completion_time_ms"],
                           results[("low", "IndependentMultiAgent")]["task_completion_time_ms"])
        self.assertEqual(0, results[("high", "IndependentMultiAgent")]["conflict_counts"]["C3"])
        self.assertEqual(results[("high", "IndependentMultiAgent")]["task_completion_time_ms"],
                         results[("high", "ConstraintCoordinator")]["task_completion_time_ms"])


if __name__ == "__main__":
    unittest.main()
