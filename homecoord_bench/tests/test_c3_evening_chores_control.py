"""Guard the low-urgency negative control and its capacity-only pairing."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_c3_review_candidates import _without_factor
from probe_c3_evening_chores_control import PRESSURES, make_candidates, run
from runtime.scheduling_oracle import ideal_schedule


class C3EveningChoresControlTests(unittest.TestCase):
    def test_only_capacity_changes_and_all_conditions_have_slack(self):
        episodes = make_candidates()
        self.assertEqual(len(PRESSURES), len(episodes))
        self.assertTrue(all(_without_factor(episode) == _without_factor(episodes[0])
                            for episode in episodes[1:]))
        for episode in episodes:
            schedule = ideal_schedule(episode)
            self.assertIsNotNone(schedule)
            by_id = {task["task_id"]: task for task in episode["task_stream"]}
            self.assertTrue(all(item["finish_ms"] < by_id[item["task_id"]]["completion_deadline_ms"]
                                for item in schedule))

    def test_control_catches_unnecessary_wait_and_has_no_privileged_future(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(90, len(report["rows"]))
        self.assertEqual(0, report["new_api_calls"])
        low = report["summary"]["0.8"]
        self.assertEqual(6, low["IndependentMultiAgent"]["all_deadlines_met"])
        self.assertEqual(6, low["DeadlineAwareCoordinator"]["all_deadlines_met"])
        self.assertGreater(
            low["DeadlineAwareCoordinator"]["median_first_action_ms"],
            low["IndependentMultiAgent"]["median_first_action_ms"],
        )
        moderate = report["summary"]["1.2"]
        self.assertEqual(6, moderate["ObservedTaskFeasibilityCoordinator"]["all_deadlines_met"])


if __name__ == "__main__":
    unittest.main()
