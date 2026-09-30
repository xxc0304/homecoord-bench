"""Checks for the online-information comparison, not benchmark performance claims."""

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_information_boundary import SOURCE, run
from probe_c3_blinded_live_pilot import _paired_requests
from audit_c3_online_information_contract import _pair_isolation, run as audit_online_contract
from probe_c3_future_pair import make_pair
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_uncertain_arrival_grid import make_arrival_case
from probe_c3_structural_generalization import make_episode_from_specs
from probe_c3_three_load import ScriptedProposalClient
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request


class C3InformationBoundaryTests(unittest.TestCase):
    def test_online_contract_audit_and_pair_mutation(self):
        if not SOURCE.exists():
            self.skipTest("saved concurrent model proposals are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = audit_online_contract(output=Path(directory) / "audit.json")
        self.assertEqual(108, report["paired_policy_conditions_checked"])
        self.assertTrue(report["all_pre_release_requests_identical_within_pair"])
        self.assertTrue(report["all_pre_release_execution_traces_identical_within_pair"])
        base = make_episode_from_specs(
            "KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2
        )
        absent = make_arrival_case(base, None)
        present = make_arrival_case(base, 60)
        present["home"]["resources"]["max_power_kw"] += 0.5
        self.assertIn("paired capacity changed", _pair_isolation(absent, present, 60))

    def test_blind_mode_fails_closed_for_ambiguous_future_goal(self):
        episode = make_pair(make_episode_from_specs(
            "KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2
        ), True)
        episode["simulation"]["blind_future_task_arrivals"] = True
        future = next(task for task in episode["task_stream"]
                      if task["task_id"] == "boil_water")
        future["required_action"]["target"] = "oven"
        task = next(task for task in episode["task_stream"]
                    if task["task_id"] == "bake_meal")
        agent = next(agent for agent in episode["agents"]
                     if agent["agent_id"] == task["agent_id"])
        agent = deepcopy(agent)
        agent["goal_visibility"] = "all"
        with self.assertRaisesRegex(ValueError, "cannot disambiguate"):
            build_agent_request(
                episode, agent, task, architecture="IndependentMultiAgent",
                current_time_ms=0, released_task_ids={"bake_meal", "wash_dishes"},
            )

    def test_live_pilot_requests_hide_future_before_release(self):
        for template_id in TEMPLATES:
            requests, metadata = _paired_requests(template_id)
            self.assertEqual(len(TEMPLATES[template_id]), len(requests))
            urgent_target = next(
                spec.device for spec in TEMPLATES[template_id]
                if spec.task_id == metadata["urgent_id"]
            )
            for task_id in metadata["initially_released"]:
                request = requests[task_id]
                self.assertNotIn(
                    f"devices.{urgent_target}",
                    [goal["path"] for goal in request["goals"]],
                )
                self.assertNotIn("FUTURE-URGENT", request["episode_id"])

    def test_unreleased_urgent_goal_is_hidden_from_agent_request(self):
        base = make_episode_from_specs(
            "KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.6
        )
        absent = make_pair(base, False)
        present = make_pair(base, True)
        for episode in (absent, present):
            episode["simulation"]["blind_future_task_arrivals"] = True
        requests = []
        for episode in (absent, present):
            task = next(item for item in episode["task_stream"]
                        if item["task_id"] == "bake_meal")
            agent = next(item for item in episode["agents"]
                         if item["agent_id"] == task["agent_id"])
            requests.append(build_agent_request(
                episode, agent, task, architecture="ObservedTaskFeasibilityCoordinator",
                current_time_ms=0, request_id="public-request",
                released_task_ids={"bake_meal", "wash_dishes"},
            ))
        self.assertEqual(requests[0], requests[1])
        self.assertNotIn("devices.kettle", [goal["path"] for goal in requests[1]["goals"]])

    def test_released_task_scheduler_does_not_require_future_prior(self):
        episode = make_arrival_case(
            make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2),
            None,
        )
        with self.assertRaisesRegex(ValueError, "shared safety gate"):
            run_event_simulation(
                episode, ScriptedProposalClient({}),
                "ObservedTaskFeasibilityCoordinator", "",
            )

    def test_paired_probe_keeps_the_privileged_prior_separate(self):
        if not SOURCE.exists():
            self.skipTest("saved concurrent model proposals are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(378, len(report["rows"]))
        self.assertEqual(0, report["new_api_calls"])
        self.assertEqual("RobustReserveCoordinator", report["future_metadata_given_only_to"])
        high = report["summary"]["KITCHEN_CIRCUIT"]["1.6"]
        self.assertEqual(0, high["present"]["ObservedTaskFeasibilityCoordinator"]["all_deadlines_met"])
        self.assertEqual(18, high["present"]["RobustReserveCoordinator"]["all_deadlines_met"])
        self.assertGreater(
            high["absent"]["RobustReserveCoordinator"]["median_first_action_ms"],
            high["absent"]["ObservedTaskFeasibilityCoordinator"]["median_first_action_ms"],
        )


if __name__ == "__main__":
    unittest.main()
