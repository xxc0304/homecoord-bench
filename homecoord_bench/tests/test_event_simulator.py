"""Regression tests for deferred physical effects in the event simulator."""

import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import load_json  # noqa: E402
from audit_event_episode_validity import audit as audit_episode_validity  # noqa: E402
from audit_event_grounding import audit as audit_grounding  # noqa: E402
from probe_physical_capacity_v2 import make_episode as make_physical_episode  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402
from runtime.episode_validation import validate_event_episode  # noqa: E402
from runtime.protocol import build_agent_request  # noqa: E402


class EventSimulatorTests(unittest.TestCase):
    def load_pair(self):
        return load_json(BENCH_ROOT / "data" / "pilot_pairs_v1" / "HC-PAIR-C1-HVAC-CONFLICT.json")

    def test_seed_actions_are_grounded_in_episode_data(self):
        for path in sorted((BENCH_ROOT / "data" / "seeds").glob("*.json")):
            episode = load_json(path)
            groundings = episode.get("action_grounding", [])
            self.assertTrue(groundings, path.name)
            self.assertTrue(all(
                "duration_ms" in grounding
                and "power_kw" in grounding
                and "start_effects" in grounding
                and "completion_effects" in grounding
                for grounding in groundings
            ), path.name)
            agents = {agent["agent_id"]: agent for agent in episode["agents"]}
            for task in episode["task_stream"]:
                request = build_agent_request(
                    episode, agents[task["agent_id"]], task,
                    architecture="IndependentMultiAgent",
                    current_time_ms=task["release_at_ms"],
                    current_state=episode["initial_state"]["values"],
                    state_version=episode["initial_state"]["version"],
                )
                decision = DryRunClient().decide(request)
                for action in decision["actions"]:
                    self.assertTrue(any(
                        item["agent_id"] == task["agent_id"]
                        and item["task_id"] == task["task_id"]
                        and item.get("operation", "*") in {"*", action["operation"]}
                        for item in groundings
                    ), f"{path.name}: {task['task_id']} {action['operation']}")
            trace, _ = run_event_simulation(
                episode, DryRunClient(), "IndependentMultiAgent", ""
            )
            started_tasks = {
                event["task_id"] for event in trace["events"]
                if event["type"] == "action_started"
            }
            self.assertEqual(
                {task["task_id"] for task in episode["task_stream"]},
                started_tasks,
                path.name,
            )

    def test_all_current_dry_run_proposals_have_episode_grounding(self):
        report = audit_grounding()
        groups = report["groups"].values()
        self.assertEqual(68, sum(group["dry_run_proposal_count"] for group in groups))
        self.assertEqual(68, sum(group["grounded_dry_run_proposal_count"] for group in groups))
        self.assertEqual(0, sum(group["ungrounded_dry_run_proposal_count"] for group in groups))
        self.assertEqual(34, report["totals"]["episode_count"])
        self.assertEqual(89, report["totals"]["grounding_count"])
        self.assertEqual(51, report["totals"]["long_action_count_ge_1000ms"])
        self.assertEqual(25, report["totals"]["long_action_explicit_phase_count"])
        self.assertEqual(26, report["totals"]["long_action_missing_explicit_phase_count"])
        self.assertEqual(7, report["totals"]["episode_with_exogenous_events_count"])
        self.assertEqual(9, report["totals"]["exogenous_event_count"])
        self.assertEqual(4, report["totals"]["completion_deadline_task_count"])

    def test_all_current_episode_files_pass_runtime_validation(self):
        report = audit_episode_validity()
        self.assertEqual(34, report["episode_count"])
        self.assertEqual(34, report["valid_count"])
        self.assertEqual(0, report["invalid_count"])

    def test_coordinator_preflights_completion_effects(self):
        episode = self.load_pair()
        _, independent = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", ""
        )
        trace, coordinated = run_event_simulation(
            episode, DryRunClient(), "RuleCoordinator", ""
        )

        self.assertEqual(1, independent["completion_constraint_violation_count"])
        self.assertFalse(independent["process_valid_success"])
        self.assertEqual(0, coordinated["completion_constraint_violation_count"])
        self.assertTrue(coordinated["process_valid_success"])
        self.assertTrue(any(
            event.get("reason") == "predicted_completion_constraint_violation"
            for event in trace["events"] if event["type"] == "action_rejected"
        ))

    def test_goal_state_change_is_visible_at_completion_not_start(self):
        episode = self.load_pair()
        trace, result = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", ""
        )
        started = next(event for event in trace["events"]
                       if event["type"] == "action_started" and event["task_id"] == "comfort_cool")
        completed = next(event for event in trace["events"]
                         if event["type"] == "action_completed" and event["task_id"] == "comfort_cool")
        self.assertLess(started["timestamp_ms"], completed["timestamp_ms"])
        self.assertEqual("cool_24", completed["effects"]["devices.living_hvac"])
        self.assertEqual(24, trace["final_state"]["living_room"]["temperature_c"])
        self.assertEqual(6101, result["first_effective_action_latency_ms"])

    def test_device_start_latency_is_separate_from_goal_progress_latency(self):
        episode = make_physical_episode("conflict")
        trace, result = run_event_simulation(
            episode, DryRunClient(), "ConstraintCoordinator", ""
        )
        first_started = min(
            event["timestamp_ms"] for event in trace["events"]
            if event["type"] == "action_started"
        )

        self.assertEqual(first_started, result["first_action_start_latency_ms"])
        self.assertGreater(
            result["first_goal_progress_latency_ms"],
            result["first_action_start_latency_ms"],
        )
        self.assertEqual(
            result["first_goal_progress_latency_ms"],
            result["first_effective_action_latency_ms"],
        )

    def test_exogenous_change_during_operation_is_counted_as_unsafe_interval(self):
        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M17.json")
        trace, result = run_event_simulation(
            episode, DryRunClient(), "ConstraintCoordinator", ""
        )

        rain = next(event for event in trace["events"]
                    if event["type"] == "state_update" and event.get("source") == "rain_started")
        completion = next(event for event in trace["events"]
                          if event["type"] == "action_completed" and event["task_id"] == "water_garden")
        self.assertTrue(rain["constraint_violation_started"])
        self.assertTrue(completion["constraint_violation_resolved"])
        self.assertEqual(1, result["state_constraint_violation_episode_count"])
        self.assertEqual(0, result["completion_constraint_violation_count"])
        self.assertEqual(completion["timestamp_ms"] - rain["timestamp_ms"],
                         result["state_constraint_violation_duration_ms"])
        self.assertEqual(1, result["in_flight_precondition_invalidated_action_count"])
        self.assertEqual("rain_started", result["in_flight_precondition_invalidations"][0]["trigger_event"])
        self.assertEqual("exogenous_update", result["in_flight_precondition_invalidations"][0]["trigger_kind"])
        self.assertEqual(0, result["cross_agent_in_flight_precondition_invalidated_action_count"])
        self.assertEqual(1, result["unsafe_state_onset_during_action_count"])
        self.assertEqual("water_garden", result["unsafe_state_onsets_during_action"][0]["active_task_ids"][0])
        self.assertFalse(result["process_valid_success"])

    def test_other_agents_start_or_completion_can_invalidate_an_in_flight_action(self):
        for phase in ("start_effects", "completion_effects"):
            with self.subTest(phase=phase):
                episode = load_json(
                    BENCH_ROOT / "revision_drafts" / "20260927" /
                    "HC-PAIR-C1-HVAC-CONFLICT.json"
                )
                comfort_task = next(task for task in episode["task_stream"]
                                    if task["task_id"] == "comfort_cool")
                comfort_task["action_template"]["requires"] = [{
                    "path": "devices.living_hvac", "op": "neq", "value": "forced_off",
                }]
                energy_grounding = next(
                    item for item in episode["action_grounding"]
                    if item["task_id"] == "peak_off"
                )
                energy_grounding["start_effects"] = {}
                energy_grounding["completion_effects"] = {}

                _, control = run_event_simulation(
                    episode, DryRunClient(), "IndependentMultiAgent", ""
                )
                self.assertEqual(0, control["in_flight_precondition_invalidated_action_count"])

                energy_grounding[phase] = {"devices.living_hvac": "forced_off"}
                trace, result = run_event_simulation(
                    episode, DryRunClient(), "IndependentMultiAgent", ""
                )
                trigger = "action_started" if phase == "start_effects" else "action_completed"
                change_event = next(
                    event for event in trace["events"]
                    if event["type"] == trigger and event["task_id"] == "peak_off"
                )
                invalidation = result["in_flight_precondition_invalidations"][0]

                self.assertEqual(1, result["in_flight_precondition_invalidated_action_count"])
                self.assertEqual(1, result["cross_agent_in_flight_precondition_invalidated_action_count"])
                self.assertEqual(trigger, invalidation["trigger_kind"])
                self.assertEqual(trigger, invalidation["trigger_event"])
                self.assertEqual("comfort_cool", invalidation["task_id"])
                self.assertEqual("peak_off", invalidation["trigger_task_id"])
                self.assertEqual("EnergyAgent", invalidation["trigger_agent_id"])
                self.assertTrue(invalidation["cross_agent"])
                self.assertEqual(change_event["timestamp_ms"], invalidation["timestamp_ms"])
                self.assertEqual(1, result["in_flight_precondition_invalidation_source_counts"][trigger])

    def test_first_in_flight_invalidation_source_is_counted_once(self):
        episode = load_json(
            BENCH_ROOT / "revision_drafts" / "20260927" /
            "HC-PAIR-C1-HVAC-CONFLICT.json"
        )
        comfort_task = next(task for task in episode["task_stream"]
                            if task["task_id"] == "comfort_cool")
        comfort_task["action_template"]["requires"] = [{
            "path": "devices.living_hvac", "op": "neq", "value": "forced_off",
        }]
        episode["exogenous_events"] = [
            {"at_ms": 450, "event": "hvac_restarts", "patch": {"devices.living_hvac": "cooling"}},
            {"at_ms": 500, "event": "hvac_stops_again", "patch": {"devices.living_hvac": "forced_off"}},
        ]
        energy_grounding = next(
            item for item in episode["action_grounding"]
            if item["task_id"] == "peak_off"
        )
        energy_grounding["start_effects"] = {"devices.living_hvac": "forced_off"}
        energy_grounding["completion_effects"] = {}

        _, result = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", ""
        )
        self.assertEqual(1, result["in_flight_precondition_invalidated_action_count"])
        self.assertEqual("action_started", result["in_flight_precondition_invalidations"][0]["trigger_kind"])
        self.assertEqual(1, result["cross_agent_in_flight_precondition_invalidated_action_count"])

    def test_state_change_before_action_start_is_reported_separately(self):
        class BoundaryLatencyClient(DryRunClient):
            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                self.last_latency_ms = 400
                return decision

        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M16.json")
        _, result = run_event_simulation(
            episode, BoundaryLatencyClient(), "ConstraintCoordinator", ""
        )

        self.assertGreaterEqual(result["stale_at_action_start_count"], 1)
        self.assertEqual(0, result["in_flight_precondition_invalidated_action_count"])
        self.assertEqual(0, result["unsafe_state_onset_during_action_count"])

        class JustBeforeBoundaryClient(DryRunClient):
            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                self.last_latency_ms = 399
                return decision

        trace, before_event = run_event_simulation(
            episode, JustBeforeBoundaryClient(), "ConstraintCoordinator", ""
        )
        clean_start = next(
            event for event in trace["events"]
            if event["type"] == "action_started" and event["task_id"] == "bedroom_clean"
        )
        self.assertEqual(499, clean_start["timestamp_ms"])
        self.assertEqual(0, before_event["stale_at_action_start_count"])
        self.assertEqual(1, before_event["in_flight_precondition_invalidated_action_count"])
        self.assertEqual(1, before_event["unsafe_state_onset_during_action_count"])

    def test_completion_after_external_state_change_counts_unsafe_in_flight_outcome(self):
        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M18.json")
        trace, result = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", ""
        )

        completion = next(
            event for event in trace["events"]
            if event["type"] == "action_completed" and event["task_id"] == "lock_entry"
        )
        self.assertTrue(completion.get("constraint_violation_started"))
        self.assertEqual(1, result["unsafe_state_onset_during_action_count"])
        self.assertEqual("action_completed", result["unsafe_state_onsets_during_action"][0]["trigger_event"])

    def test_c4_rule_must_reference_a_real_task_precondition(self):
        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M16.json")
        episode["conflict_rules"] = [{
            "type": "C4",
            "task_id": "bedroom_clean",
            "invalidating_conditions": [
                {"path": "bedroom.occupied", "op": "eq", "value": True},
            ],
        }]

        errors = validate_event_episode(episode)
        self.assertTrue(any("must appear in task_stream" in error for error in errors))

    def test_replayed_calls_return_in_latency_order_not_release_order(self):
        class UnequalLatencyClient(DryRunClient):
            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                self.last_latency_ms = (
                    900 if agent_request["task"]["task_id"] == "comfort_cool" else 100
                )
                return decision

        episode = self.load_pair()
        trace, result = run_event_simulation(
            episode, UnequalLatencyClient(), "IndependentMultiAgent", ""
        )
        repeated_trace, repeated_result = run_event_simulation(
            episode, UnequalLatencyClient(), "IndependentMultiAgent", ""
        )
        returned = [event for event in trace["events"] if event["type"] == "proposal_returned"]

        self.assertEqual(trace, repeated_trace)
        self.assertEqual(result, repeated_result)
        self.assertEqual(["peak_off", "comfort_cool"], [event["task_id"] for event in returned])
        self.assertEqual([300, 900], [event["timestamp_ms"] for event in returned])
        self.assertFalse(result["api_calls_concurrent"])

    def test_same_time_exogenous_update_is_visible_to_task_release(self):
        class RecordingDryRunClient(DryRunClient):
            def __init__(self):
                self.requests = []

            def decide(self, agent_request, instructions=""):
                self.requests.append(agent_request)
                return super().decide(agent_request, instructions)

        episode = self.load_pair()
        episode["exogenous_events"] = [{
            "at_ms": 200,
            "event": "device_changed",
            "patch": {"devices.living_hvac": "externally_off"},
        }]
        client = RecordingDryRunClient()
        run_event_simulation(episode, client, "IndependentMultiAgent", "")

        energy_request = next(request for request in client.requests
                              if request["task"]["task_id"] == "peak_off")
        self.assertEqual("externally_off", energy_request["state"]["devices"]["living_hvac"])
        self.assertEqual(episode["initial_state"]["version"] + 1, energy_request["state_version"])

    def test_same_time_update_completion_and_release_have_documented_order(self):
        class RecordingDryRunClient(DryRunClient):
            def __init__(self):
                self.requests = []

            def decide(self, agent_request, instructions=""):
                self.requests.append(agent_request)
                return super().decide(agent_request, instructions)

        episode = self.load_pair()
        baseline_trace, _ = run_event_simulation(
            episode, DryRunClient(), "IndependentMultiAgent", ""
        )
        completion_time = next(
            event["timestamp_ms"] for event in baseline_trace["events"]
            if event["type"] == "action_completed" and event["task_id"] == "comfort_cool"
        )
        episode["task_stream"][1]["release_at_ms"] = completion_time
        episode["exogenous_events"] = [{
            "at_ms": completion_time,
            "event": "simultaneous_device_update",
            "patch": {"devices.living_hvac": "external_override"},
        }]

        client = RecordingDryRunClient()
        trace, _ = run_event_simulation(
            episode, client, "IndependentMultiAgent", ""
        )
        same_time = [event for event in trace["events"]
                     if event["timestamp_ms"] == completion_time
                     and event["type"] in {"state_update", "action_completed", "task_released"}]
        self.assertEqual(
            ["state_update", "action_completed", "task_released"],
            [event["type"] for event in same_time],
        )
        self.assertEqual("simultaneous_device_update", same_time[0]["source"])
        self.assertEqual("cool_24", same_time[1]["effects"]["devices.living_hvac"])

        energy_request = next(request for request in client.requests
                              if request["task"]["task_id"] == "peak_off")
        self.assertEqual("cool_24", energy_request["state"]["devices"]["living_hvac"])
        self.assertEqual(same_time[1]["new_state_version"], energy_request["state_version"])

    def test_invalid_event_timestamps_and_duplicate_task_ids_fail_before_execution(self):
        episode = self.load_pair()
        episode["exogenous_events"] = [{"at_ms": -1, "patch": {}}]
        with self.assertRaisesRegex(ValueError, r"exogenous_events\[0\]\.at_ms"):
            run_event_simulation(episode, DryRunClient(), "IndependentMultiAgent", "")

        episode = self.load_pair()
        episode["task_stream"].append(dict(episode["task_stream"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate task_id"):
            run_event_simulation(episode, DryRunClient(), "IndependentMultiAgent", "")

    def test_action_exceeding_total_capacity_is_rejected_without_crashing(self):
        episode = make_physical_episode("conflict")
        capacity_rule = next(rule for rule in episode["conflict_rules"]
                             if rule["type"] == "C3")
        capacity_rule["capacity"] = 1.0
        trace, result = run_event_simulation(
            episode, DryRunClient(), "ConstraintCoordinator", ""
        )

        decisions = [event for event in trace["events"]
                     if event["type"] == "coordination_decision"]
        rejects = [event for event in trace["events"]
                   if event["type"] == "action_rejected"]
        self.assertEqual(2, sum(event.get("reason") == "resource_capacity_exceeded"
                                for event in decisions))
        self.assertEqual(2, sum(event.get("reason") == "resource_capacity_exceeded"
                                for event in rejects))
        self.assertFalse(any(event["type"] == "action_started" for event in trace["events"]))
        self.assertEqual(2, result["rejected_action_count"])
        self.assertFalse(result["process_valid_success"])

    def test_start_effect_does_not_make_its_own_action_look_stale(self):
        episode = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M16.json")
        episode["task_stream"][0]["action_template"]["requires"].append({
            "path": "devices.bedroom_robot", "op": "eq", "value": "idle",
        })
        _, result = run_event_simulation(
            episode, DryRunClient(), "ConstraintCoordinator", ""
        )

        self.assertEqual(0, result["precondition_violations_at_start"])
        self.assertEqual(0, result["conflict_counts"]["C4"])

    def test_capacity_pair_changes_overlap_and_preserves_safe_parallelism(self):
        conflict = make_physical_episode("conflict")
        control = make_physical_episode("control")
        _, independent = run_event_simulation(
            conflict, DryRunClient(), "IndependentMultiAgent", ""
        )
        coordinated_trace, coordinated = run_event_simulation(
            conflict, DryRunClient(), "ConstraintCoordinator", ""
        )
        control_trace, control_result = run_event_simulation(
            control, DryRunClient(), "ConstraintCoordinator", ""
        )

        self.assertEqual(1, independent["conflict_counts"]["C3"])
        self.assertEqual(0, coordinated["conflict_counts"]["C3"])
        self.assertTrue(coordinated["process_valid_success"])
        self.assertTrue(any(
            event.get("reason") == "resource_capacity"
            for event in coordinated_trace["events"] if event["type"] == "coordination_decision"
        ))
        self.assertEqual(0, control_result["conflict_counts"]["C3"])
        self.assertFalse(any(
            event.get("reason") == "resource_capacity"
            for event in control_trace["events"] if event["type"] == "coordination_decision"
        ))

    def test_capacity_order_can_trade_safety_for_an_urgent_task_deadline(self):
        class WaterProposalReturnsFirst(DryRunClient):
            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                self.last_latency_ms = (
                    1200 if agent_request["task"]["task_id"] == "heat_water" else 1400
                )
                return decision

        def with_ev_deadline(condition):
            episode = make_physical_episode(condition)
            deadline = 18_600_000
            episode["initial_state"]["values"]["vehicle"]["departure_deadline_ms"] = deadline
            next(task for task in episode["task_stream"] if task["task_id"] == "charge_ev")[
                "completion_deadline_ms"
            ] = deadline
            return episode

        conflict = with_ev_deadline("conflict")
        control = with_ev_deadline("control")
        _, unsafe = run_event_simulation(
            conflict, WaterProposalReturnsFirst(), "IndependentMultiAgent", ""
        )
        _, safe_but_late = run_event_simulation(
            conflict, WaterProposalReturnsFirst(), "ConstraintCoordinator", ""
        )
        _, safe_control = run_event_simulation(
            control, WaterProposalReturnsFirst(), "ConstraintCoordinator", ""
        )
        deadline_trace, deadline_aware = run_event_simulation(
            conflict, WaterProposalReturnsFirst(), "DeadlineAwareCoordinator", ""
        )

        self.assertEqual(1, unsafe["conflict_counts"]["C3"])
        self.assertTrue(unsafe["task_deadline_met"]["charge_ev"])
        self.assertTrue(safe_but_late["process_valid_success"])
        self.assertFalse(safe_but_late["task_deadline_met"]["charge_ev"])
        self.assertFalse(safe_but_late["timely_process_valid_success"])
        self.assertTrue(safe_control["task_deadline_met"]["charge_ev"])
        self.assertEqual(0, deadline_aware["conflict_counts"]["C3"])
        self.assertTrue(deadline_aware["process_valid_success"])
        self.assertTrue(deadline_aware["timely_process_valid_success"])
        self.assertEqual(
            ["charge_ev", "heat_water"],
            [event["task_id"] for event in deadline_trace["events"]
             if event["type"] == "coordination_decision"],
        )

    def test_deadline_baseline_does_not_wait_for_unreleased_future_tasks(self):
        episode = make_physical_episode("conflict")
        water_task = next(task for task in episode["task_stream"]
                          if task["task_id"] == "heat_water")
        water_task["release_at_ms"] = 500
        trace, _ = run_event_simulation(
            episode, DryRunClient(), "DeadlineAwareCoordinator", ""
        )

        first_start = next(event for event in trace["events"]
                           if event["type"] == "action_started")
        self.assertEqual("charge_ev", first_start["task_id"])
        self.assertLess(first_start["timestamp_ms"], water_task["release_at_ms"])

    def test_proposal_return_order_changes_arrival_policy_but_edf_is_order_robust(self):
        class TaskLatencyClient(DryRunClient):
            def __init__(self, latency_by_task):
                self.latency_by_task = latency_by_task

            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                self.last_latency_ms = self.latency_by_task[agent_request["task"]["task_id"]]
                return decision

        episode = make_physical_episode("conflict")

        def run(policy, latency_by_task):
            return run_event_simulation(
                episode, TaskLatencyClient(latency_by_task), policy, ""
            )

        water_first_trace, water_first = run(
            "ConstraintCoordinator", {"charge_ev": 600, "heat_water": 100}
        )
        ev_first_trace, ev_first = run(
            "ConstraintCoordinator", {"charge_ev": 100, "heat_water": 500}
        )
        deadline_trace, deadline_aware = run(
            "DeadlineAwareCoordinator", {"charge_ev": 600, "heat_water": 100}
        )

        self.assertEqual(
            ["heat_water", "charge_ev"],
            [event["task_id"] for event in water_first_trace["events"]
             if event["type"] == "proposal_returned"],
        )
        self.assertEqual(
            ["charge_ev", "heat_water"],
            [event["task_id"] for event in ev_first_trace["events"]
             if event["type"] == "proposal_returned"],
        )
        self.assertFalse(water_first["task_deadline_met"]["charge_ev"])
        self.assertTrue(ev_first["task_deadline_met"]["charge_ev"])
        self.assertTrue(deadline_aware["timely_process_valid_success"])
        self.assertEqual(
            "charge_ev",
            next(event["task_id"] for event in deadline_trace["events"]
                 if event["type"] == "action_started"),
        )


if __name__ == "__main__":
    unittest.main()
