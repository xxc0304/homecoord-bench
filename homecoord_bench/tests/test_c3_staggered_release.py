"""Audit saved-proposal alignment and physical feasibility after release shifts."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_staggered_release import (
    SCENARIOS, SOURCE, ideal_schedule, release_order_records, run,
    set_release_pattern,
)
from probe_c3_structural_generalization import make_episode_from_specs


class C3StaggeredReleaseTests(unittest.TestCase):
    def test_saved_decisions_follow_actual_release_order(self):
        episode = make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2)
        changed = set_release_pattern(episode, "urgent_late_1m")
        records = {task["task_id"]: {"request": {"task": {"task_id": task["task_id"]}}}
                   for task in changed["task_stream"]}
        ordered = release_order_records(changed, records)
        self.assertEqual(["bake_meal", "wash_dishes", "boil_water"],
                         [row["request"]["task"]["task_id"] for row in ordered])

    def test_ideal_schedules_obey_release_capacity_and_deadlines(self):
        for template_id, specs in TEMPLATES.items():
            for pressure in (0.8, 1.2, 1.6):
                for scenario in SCENARIOS:
                    with self.subTest(template=template_id, pressure=pressure, scenario=scenario):
                        episode = set_release_pattern(
                            make_episode_from_specs(template_id, specs, pressure), scenario
                        )
                        schedule = ideal_schedule(episode)
                        self.assertIsNotNone(schedule)
                        tasks = {task["task_id"]: task for task in episode["task_stream"]}
                        self.assertEqual(set(tasks), {item["task_id"] for item in schedule})
                        for item in schedule:
                            task = tasks[item["task_id"]]
                            self.assertGreaterEqual(item["start_ms"], task["release_at_ms"])
                            self.assertEqual(item["finish_ms"] - item["start_ms"],
                                             task["action_template"]["duration_ms"])
                            self.assertLessEqual(item["finish_ms"], task["completion_deadline_ms"])
                        for time in {item["start_ms"] for item in schedule}:
                            load = sum(tasks[item["task_id"]]["action_template"]["power_kw"]
                                       for item in schedule
                                       if item["start_ms"] <= time < item["finish_ms"])
                            self.assertLessEqual(
                                load, episode["home"]["resources"]["max_power_kw"] + 1e-9
                            )

    def test_common_release_matches_saved_pilot(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(360, len(report["rows"]))
        original = json.loads(SOURCE.read_text(encoding="utf-8"))
        latency_lookup = {
            (batch["template_id"], batch["repetition"]): {
                task_id: record["logical_latency_ms"]
                for task_id, record in batch["sample"]["records"].items()
            }
            for batch in original["batches"]
        }
        lookup = {
            (row["template_id"], row["repetition"], row["pressure"], row["policy"]): row
            for row in original["replays"]
        }
        for row in report["rows"]:
            self.assertEqual(
                latency_lookup[(row["template_id"], row["repetition"])],
                row["model_latency_by_task_ms"],
            )
            if row["scenario"] == "co_release" and row["policy"] != "GateRetryRule":
                peer = lookup[(row["template_id"], row["repetition"],
                               row["pressure"], row["policy"])]
                self.assertEqual(row["all_deadlines_met"], peer["all_deadlines_met"])
                self.assertEqual(row["first_action_start_latency_ms"],
                                 peer["first_action_start_latency_ms"])


if __name__ == "__main__":
    unittest.main()
