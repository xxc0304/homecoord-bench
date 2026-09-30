"""Deadline perturbation must preserve the original saved replay at factor one."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_deadline_slack_sensitivity import SOURCE, change_deadline_slack, run
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_structural_generalization import make_episode_from_specs


class C3DeadlineSlackSensitivityTests(unittest.TestCase):
    def test_factor_one_matches_original_model_replay(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(360, len(report["rows"]))
        original = json.loads(SOURCE.read_text(encoding="utf-8"))
        lookup = {
            (row["template_id"], row["repetition"], row["pressure"], row["policy"]): row
            for row in original["replays"]
        }
        for row in report["rows"]:
            if row["slack_factor"] == 1.0:
                peer = lookup[(row["template_id"], row["repetition"],
                               row["pressure"], row["policy"])]
                self.assertEqual(row["all_deadlines_met"], peer["all_deadlines_met"])
                self.assertEqual(row["first_action_start_latency_ms"],
                                 peer["first_action_start_latency_ms"])

    def test_only_deadlines_and_visible_goal_change(self):
        episode = make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2)
        modified = change_deadline_slack(episode, 0.75)
        for original, changed in zip(episode["task_stream"], modified["task_stream"]):
            self.assertEqual(original["action_template"], changed["action_template"])
            self.assertEqual(original["priority"], changed["priority"])
            self.assertEqual(original["release_at_ms"], changed["release_at_ms"])
            duration = original["action_template"]["duration_ms"]
            expected = duration + round((original["completion_deadline_ms"] - duration) * 0.75)
            self.assertEqual(expected, changed["completion_deadline_ms"])


if __name__ == "__main__":
    unittest.main()
