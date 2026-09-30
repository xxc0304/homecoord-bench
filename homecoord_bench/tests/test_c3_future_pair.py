"""Future-urgent pairs change one event while preserving nonurgent work."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_future_pair import (
    HOLD_UNTIL_MS, SOURCE, make_pair, method_policy_and_hold, run,
)
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_staggered_release import ideal_schedule
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation
from probe_c3_three_load import ScriptedProposalClient


class C3FuturePairTests(unittest.TestCase):
    def test_pair_keeps_nonurgent_work_and_budget_identical(self):
        for template_id, specs in TEMPLATES.items():
            base = make_episode_from_specs(template_id, specs, 1.6)
            absent, present = make_pair(base, False), make_pair(base, True)
            self.assertEqual([], validate_event_episode(absent))
            self.assertEqual([], validate_event_episode(present))
            self.assertIsNotNone(ideal_schedule(absent))
            self.assertIsNotNone(ideal_schedule(present))
            self.assertEqual(absent["home"]["resources"]["max_power_kw"],
                             present["home"]["resources"]["max_power_kw"])
            present_tasks = {task["task_id"]: task for task in present["task_stream"]}
            self.assertEqual(len(absent["task_stream"]) + 1, len(present_tasks))
            for task in absent["task_stream"]:
                self.assertEqual(task, present_tasks[task["task_id"]])

    def test_unknown_hold_is_identical_across_pair(self):
        self.assertEqual(("FixedHoldCoordinator", HOLD_UNTIL_MS),
                         method_policy_and_hold("FixedHoldUnknown", False))
        self.assertEqual(("FixedHoldCoordinator", HOLD_UNTIL_MS),
                         method_policy_and_hold("FixedHoldUnknown", True))
        self.assertEqual(("FixedHoldCoordinator", 0),
                         method_policy_and_hold("ConditionalHoldAnnounced", False))
        self.assertEqual(("FixedHoldCoordinator", HOLD_UNTIL_MS),
                         method_policy_and_hold("ConditionalHoldAnnounced", True))

    def test_hold_policy_requires_valid_clock(self):
        episode = make_pair(
            make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2),
            False,
        )
        episode["simulation"]["hold_until_ms"] = True
        with self.assertRaisesRegex(ValueError, "hold_until_ms"):
            run_event_simulation(episode, ScriptedProposalClient({}),
                                 "FixedHoldCoordinator", "", shared_safety_gate=True)

    def test_saved_batch_counts_and_alignment(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(180, len(report["rows"]))
        saved = json.loads(SOURCE.read_text(encoding="utf-8"))
        latencies = {(batch["template_id"], batch["repetition"]): {
            task_id: record["logical_latency_ms"]
            for task_id, record in batch["sample"]["records"].items()
        } for batch in saved["batches"]}
        for row in report["rows"]:
            expected = latencies[(row["template_id"], row["repetition"])]
            if not row["future_urgent"]:
                expected = {task_id: latency for task_id, latency in expected.items()
                            if task_id in row["model_latency_by_task_ms"]}
            self.assertEqual(expected, row["model_latency_by_task_ms"])


if __name__ == "__main__":
    unittest.main()
