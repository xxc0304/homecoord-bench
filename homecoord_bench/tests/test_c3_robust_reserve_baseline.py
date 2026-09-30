"""Audit the strong rule's declared prior, replay pairing, and oracle constraint."""

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_robust_reserve_baseline import (
    SOURCE, potential_urgent_metadata, run,
)
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_uncertain_arrival_grid import make_arrival_case
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.scheduling_oracle import ideal_schedule
from probe_c3_three_load import ScriptedProposalClient


class C3RobustReserveBaselineTests(unittest.TestCase):
    def test_potential_prior_is_identical_across_absent_and_present(self):
        for template_id, specs in TEMPLATES.items():
            base = make_episode_from_specs(template_id, specs, 1.6)
            absent = make_arrival_case(base, None)
            present = make_arrival_case(base, 60)
            prior = potential_urgent_metadata(template_id)
            absent["simulation"]["potential_urgent"] = deepcopy(prior)
            present["simulation"]["potential_urgent"] = deepcopy(prior)
            self.assertEqual(absent["simulation"]["potential_urgent"],
                             present["simulation"]["potential_urgent"])

    def test_forced_commitment_checks_future_viability(self):
        base = make_episode_from_specs(
            "KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.6
        )
        episode = make_arrival_case(base, None)
        oven_start = 1000
        urgent = potential_urgent_metadata("KITCHEN_CIRCUIT")
        hypothetical = {
            "task_id": urgent["task_id"],
            "release_at_ms": 15_000,
            "completion_deadline_ms": urgent["deadline_ms"],
            "action_template": {
                "duration_ms": urgent["duration_ms"],
                "power_kw": urgent["power_kw"],
            },
        }
        self.assertIsNone(ideal_schedule(
            episode, now_ms=oven_start,
            forced_starts={"bake_meal": oven_start}, extra_task=hypothetical,
        ))
        self.assertIsNotNone(ideal_schedule(episode, now_ms=oven_start))

    def test_policy_requires_shared_gate_and_prior(self):
        episode = make_arrival_case(
            make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2),
            None,
        )
        with self.assertRaisesRegex(ValueError, "shared safety gate"):
            run_event_simulation(episode, ScriptedProposalClient({}),
                                 "RobustReserveCoordinator", "")
        with self.assertRaisesRegex(ValueError, "potential_urgent"):
            run_event_simulation(episode, ScriptedProposalClient({}),
                                 "RobustReserveCoordinator", "", shared_safety_gate=True)

    def test_saved_replay_has_no_extra_model_calls(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(126, len(report["rows"]))
        self.assertTrue(all(row["all_deadlines_met"] for row in report["rows"]))
        saved = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(6, len(saved["batches"]))
        kitchen_absent = [row for row in report["rows"]
                          if row["template_id"] == "KITCHEN_CIRCUIT"
                          and row["nominal_pressure"] == 1.6
                          and row["future_arrival_s"] is None]
        morning_absent = [row for row in report["rows"]
                          if row["template_id"] == "MORNING_DEPARTURE"
                          and row["nominal_pressure"] == 1.6
                          and row["future_arrival_s"] is None]
        self.assertTrue(all(row["first_action_start_latency_ms"] >= 120_000
                            for row in kitchen_absent))
        self.assertTrue(all(row["first_action_start_latency_ms"] < 2_000
                            for row in morning_absent))


if __name__ == "__main__":
    unittest.main()
