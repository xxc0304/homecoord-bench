"""Behavioral checks for the review-only C1/C3/C4 episode drafts."""

import sys
import json
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from make_representative_revision_drafts import make_drafts  # noqa: E402
from audit_representative_revision_drafts import changed_paths  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.episode_validation import validate_event_episode  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402
from runtime.protocol import build_agent_request  # noqa: E402


class FixedLatencyClient(DryRunClient):
    def __init__(self, latency_ms):
        self.latency_ms = latency_ms

    def decide(self, request, instructions=""):
        decision = super().decide(request, instructions)
        self.last_latency_ms = self.latency_ms
        return decision


class RepresentativeRevisionDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drafts = {episode["episode_id"]: episode for episode in make_drafts()}

    def test_drafts_are_valid_distinct_and_not_scoring_data(self):
        self.assertEqual(9, len(self.drafts))
        self.assertTrue(all(
            episode["review_status"] == "proposed_revision_not_scored"
            and not validate_event_episode(episode)
            for episode in self.drafts.values()
        ))
        self.assertEqual(9, len({episode["episode_id"] for episode in self.drafts.values()}))
        c4 = self.drafts["HC-PAIR-C4-CLEAN-INFLIGHT"]
        self.assertEqual("C4", c4["conflict_rules"][0]["type"])

    def test_c2_is_present_as_a_separate_uncalibrated_review_scenario(self):
        path = BENCH_ROOT / "revision_drafts" / "20260927" / "HC-PAIR-C2-VENT-HEAT-REVIEW.json"
        c2 = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("standalone_continuous_physics_probe", c2["scenario_type"])
        self.assertEqual("proposed_revision_not_scored", c2["review_status"])
        self.assertEqual("C2_indirect_environmental_interference", c2["conflict_family"])
        self.assertEqual([240000, 360000, 480000], c2["evaluation_deadline_ms_grid"])
        self.assertFalse(c2["provenance_and_limits"]["has_real_device_data"])
        self.assertFalse(c2["provenance_and_limits"]["has_real_model_proposals"])

    def test_coordination_delay_occurs_after_identical_proposals(self):
        safe = self.drafts["HC-PAIR-C1-HVAC-SAFE"]
        before_trace, before = run_event_simulation(
            safe, FixedLatencyClient(300), "ConstraintCoordinator", ""
        )
        after_trace, after = run_event_simulation(
            safe, FixedLatencyClient(300), "ConstraintCoordinator", "",
            coordination_delay_ms=250,
        )
        returned = lambda trace: [event["timestamp_ms"] for event in trace["events"]
                                  if event["type"] == "proposal_returned"]
        decisions = lambda trace: [event["timestamp_ms"] for event in trace["events"]
                                   if event["type"] == "coordination_decision"]
        self.assertEqual(returned(before_trace), returned(after_trace))
        self.assertEqual([time + 250 for time in decisions(before_trace)],
                         decisions(after_trace))
        self.assertEqual(before["first_action_start_latency_ms"] + 250,
                         after["first_action_start_latency_ms"])
        self.assertEqual(250, after["coordination_delay_ms"])

    def test_live_style_requests_match_declared_tool_signatures_without_answer_leak(self):
        for episode in self.drafts.values():
            agents = {agent["agent_id"]: agent for agent in episode["agents"]}
            for item in episode["tool_catalog"]:
                self.assertIn("agent_id", item)
                self.assertIn("target", item)
                self.assertIn("operation", item)
                self.assertIsInstance(item["parameters"], list)
            for task in episode["task_stream"]:
                request = build_agent_request(
                    episode, agents[task["agent_id"]], task,
                    architecture="IndependentMultiAgent",
                    current_time_ms=task["release_at_ms"],
                    current_state=episode["initial_state"]["values"],
                    state_version=episode["initial_state"]["version"],
                )
                self.assertTrue(request["allowed_tools"])
                self.assertTrue(request["available_actions"])
                self.assertTrue(all(
                    item["agent_id"] == task["agent_id"]
                    for item in request["available_actions"]
                ))
                template = task["action_template"]
                self.assertTrue(any(
                    item["target"] == template["target"]
                    and item["operation"] == template["operation"]
                    for item in request["available_actions"]
                ))
                self.assertNotIn("action_template", request["task"])
                self.assertNotIn("required_action", request["task"])

    def test_c1_pair_isolates_overlap_and_coordinator_reduces_it(self):
        conflict = self.drafts["HC-PAIR-C1-HVAC-CONFLICT"]
        safe = self.drafts["HC-PAIR-C1-HVAC-SAFE"]
        _, independent_conflict = run_event_simulation(
            conflict, DryRunClient(), "IndependentMultiAgent", ""
        )
        _, coordinated_conflict = run_event_simulation(
            conflict, DryRunClient(), "ConstraintCoordinator", ""
        )
        _, independent_safe = run_event_simulation(
            safe, DryRunClient(), "IndependentMultiAgent", ""
        )

        self.assertEqual(1, independent_conflict["conflict_counts"]["C1"])
        self.assertEqual(0, coordinated_conflict["conflict_counts"]["C1"])
        self.assertEqual(0, independent_safe["conflict_counts"]["C1"])
        self.assertTrue(coordinated_conflict["final_goal_success"])
        self.assertTrue(all(coordinated_conflict["task_service"].values()))
        self.assertEqual(5800, (
            coordinated_conflict["task_action_finish_time_ms"]["peak_off"]
            - independent_conflict["task_action_finish_time_ms"]["peak_off"]
        ))
        _, coordinated_safe = run_event_simulation(
            safe, DryRunClient(), "ConstraintCoordinator", ""
        )
        self.assertEqual(
            independent_safe["task_action_finish_time_ms"]["peak_off"],
            coordinated_safe["task_action_finish_time_ms"]["peak_off"],
        )

    def test_c3_pair_crosses_capacity_boundary_without_single_action_overload(self):
        low = self.drafts["HC-PAIR-C3-HOME-POWER-OVER-CAPACITY"]
        exact = self.drafts["HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT"]
        high = self.drafts["HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL"]
        _, independent_low = run_event_simulation(
            low, DryRunClient(), "IndependentMultiAgent", ""
        )
        _, coordinated_low = run_event_simulation(
            low, DryRunClient(), "ConstraintCoordinator", ""
        )
        _, independent_high = run_event_simulation(
            high, DryRunClient(), "IndependentMultiAgent", ""
        )
        _, independent_exact = run_event_simulation(
            exact, DryRunClient(), "IndependentMultiAgent", ""
        )
        _, coordinated_exact = run_event_simulation(
            exact, DryRunClient(), "ConstraintCoordinator", ""
        )

        self.assertEqual(1, independent_low["conflict_counts"]["C3"])
        self.assertEqual(0, coordinated_low["conflict_counts"]["C3"])
        self.assertEqual(0, independent_high["conflict_counts"]["C3"])
        self.assertEqual(0, independent_exact["conflict_counts"]["C3"])
        self.assertEqual(0, coordinated_exact["conflict_counts"]["C3"])
        self.assertEqual(
            independent_exact["task_completion_time_ms"],
            coordinated_exact["task_completion_time_ms"],
        )
        self.assertGreater(
            coordinated_low["task_completion_time_ms"],
            independent_high["task_completion_time_ms"],
        )

    def test_c4_timing_arms_separate_precommit_inflight_and_safe_controls(self):
        precommit = self.drafts["HC-PAIR-C4-CLEAN-PRECOMMIT"]
        inflight = self.drafts["HC-PAIR-C4-CLEAN-INFLIGHT"]
        no_event = self.drafts["HC-PAIR-C4-CLEAN-NO-EVENT"]
        postcomplete = self.drafts["HC-PAIR-C4-CLEAN-POSTCOMPLETE"]
        self.assertEqual(300, precommit["variant"]["proposal_latency_factor_ms"])
        self.assertEqual(300, inflight["variant"]["proposal_latency_factor_ms"])
        self.assertEqual(350, precommit["exogenous_events"][0]["at_ms"])
        self.assertEqual(500, inflight["exogenous_events"][0]["at_ms"])
        self.assertEqual(
            {"episode_id", "variant.condition", "exogenous_events[0].at_ms",
             "exogenous_events[1].at_ms"},
            set(changed_paths(precommit, inflight)),
        )

        _, before = run_event_simulation(
            precommit, FixedLatencyClient(300), "ConstraintCoordinator", ""
        )
        _, during = run_event_simulation(
            inflight, FixedLatencyClient(300), "ConstraintCoordinator", ""
        )
        _, control = run_event_simulation(
            no_event, FixedLatencyClient(300), "ConstraintCoordinator", ""
        )
        _, after = run_event_simulation(
            postcomplete, FixedLatencyClient(300), "ConstraintCoordinator", ""
        )

        self.assertEqual(1, before["stale_at_action_start_count"])
        self.assertEqual(0, before["in_flight_precondition_invalidated_action_count"])
        self.assertEqual(1, during["in_flight_precondition_invalidated_action_count"])
        self.assertEqual(1, during["unsafe_state_onset_during_action_count"])
        self.assertGreater(during["state_constraint_violation_duration_ms"], 0)
        self.assertTrue(control["final_goal_success"])
        self.assertEqual(0, control["unsafe_state_onset_during_action_count"])
        self.assertTrue(after["final_goal_success"])
        self.assertEqual(0, after["unsafe_state_onset_during_action_count"])


if __name__ == "__main__":
    unittest.main()
