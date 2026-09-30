"""Checks for paired C3 review candidates."""

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_c3_review_candidates import audit, feasible_schedule, generate, make_candidates


class C3ReviewCandidateTests(unittest.TestCase):
    def test_review_pair_isolation_and_episode_validity(self):
        self.assertEqual([], audit(make_candidates()))

    def test_manifest_counts_configurations_not_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = generate(Path(directory))
        self.assertEqual(2, manifest["template_count"])
        self.assertEqual(8, manifest["episode_configurations"])
        self.assertEqual("author_side_review_candidates_not_frozen", manifest["status"])
        self.assertEqual(8, len(manifest["ideal_feasible_schedules"]))

    def test_ideal_schedule_respects_capacity_and_deadlines(self):
        for episode in make_candidates():
            schedule = feasible_schedule(episode)
            self.assertIsNotNone(schedule)
            tasks = {task["task_id"]: task for task in episode["task_stream"]}
            self.assertEqual(set(tasks), {item["task_id"] for item in schedule})
            capacity = episode["home"]["resources"]["max_power_kw"]
            for item in schedule:
                task = tasks[item["task_id"]]
                self.assertEqual(task["action_template"]["duration_ms"],
                                 item["finish_ms"] - item["start_ms"])
                self.assertLessEqual(item["finish_ms"], task["completion_deadline_ms"])
            for time in {item["start_ms"] for item in schedule}:
                load = sum(tasks[item["task_id"]]["action_template"]["power_kw"]
                           for item in schedule
                           if item["start_ms"] <= time < item["finish_ms"])
                self.assertLessEqual(load, capacity + 1e-9)

    def test_unschedulable_candidate_is_rejected(self):
        episode = deepcopy(make_candidates()[0])
        episode["task_stream"][0]["completion_deadline_ms"] = 1
        self.assertIsNone(feasible_schedule(episode))
        self.assertTrue(any("no ideal all-deadline schedule" in error
                            for error in audit([episode])))


if __name__ == "__main__":
    unittest.main()
