import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import load_json  # noqa: E402
from run_protocol_pilot import INSTRUCTIONS  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.execution import run_closed_loop_episode  # noqa: E402
from runtime.variants import (  # noqa: E402
    direct_conflict_variants,
    indirect_conflict_variants,
    resource_capacity_variants,
    stale_action_variants,
)


class ClosedLoopTests(unittest.TestCase):
    def run_case(self, episode_id, architecture):
        episode = load_json(BENCH_ROOT / "data" / "seeds" / f"{episode_id}.json")
        return run_closed_loop_episode(
            episode,
            DryRunClient(),
            architecture,
            INSTRUCTIONS,
            synthetic_latency=True,
        )

    def run_variant(self, episode, architecture):
        return run_closed_loop_episode(
            episode,
            DryRunClient(),
            architecture,
            INSTRUCTIONS,
            synthetic_latency=True,
        )

    def test_three_architectures_have_expected_seed_discriminability(self):
        results = {}
        for architecture in ("CentralSingleAgent", "IndependentMultiAgent", "RuleCoordinator"):
            results[architecture] = [
                self.run_case(f"HC-SEED-{index:03d}", architecture)[1]
                for index in range(1, 5)
            ]
        self.assertEqual(4, sum(row["process_valid_success"] for row in results["CentralSingleAgent"]))
        self.assertEqual(2, sum(row["process_valid_success"] for row in results["IndependentMultiAgent"]))
        self.assertEqual(3, sum(row["process_valid_success"] for row in results["RuleCoordinator"]))

    def test_rule_coordinator_misses_indirect_conflict(self):
        _, result = self.run_case("HC-SEED-003", "RuleCoordinator")
        self.assertEqual(1, result["conflict_counts"]["C2"])
        self.assertFalse(result["process_valid_success"])

    def test_stale_cleaning_action_is_retried_after_resident_leaves(self):
        for architecture in ("RuleCoordinator", "CentralSingleAgent"):
            with self.subTest(architecture=architecture):
                trace, result = self.run_case("HC-SEED-004", architecture)
                decisions = [event for event in trace["events"] if event["type"] == "coordination_decision"]
                self.assertTrue(any(event.get("reason") == "stale_state" for event in decisions))
                self.assertTrue(any(event.get("decision") == "accept_retry" for event in decisions))
                self.assertTrue(result["process_valid_success"])

    def test_deferred_local_retry_is_woken_once(self):
        class DeferOnceClient(DryRunClient):
            def __init__(self):
                self.cleaning_calls = 0

            def decide(self, agent_request, instructions=""):
                if agent_request["task"]["task_id"] == "clean":
                    self.cleaning_calls += 1
                    if self.cleaning_calls == 2:
                        return {
                            "response_type": "defer", "actions": [],
                            "accepted_proposal_ids": [], "rejected_proposal_ids": [],
                            "defer_until_ms": 6000, "reason_code": "unsafe_precondition",
                        }
                return super().decide(agent_request, instructions)

        episode = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-004.json")
        trace, result = run_closed_loop_episode(
            episode, DeferOnceClient(), "RuleCoordinator", INSTRUCTIONS, synthetic_latency=True
        )
        decisions = [event for event in trace["events"] if event["type"] == "coordination_decision"]
        self.assertTrue(any(event.get("decision") == "defer_retry" for event in decisions))
        self.assertTrue(any(event.get("decision") == "accept_retry" for event in decisions))
        self.assertTrue(result["process_valid_success"])

    def test_central_serialization_adds_latency_on_safe_parallel_tasks(self):
        _, central = self.run_case("HC-SEED-001", "CentralSingleAgent")
        _, independent = self.run_case("HC-SEED-001", "IndependentMultiAgent")
        self.assertGreater(central["task_completion_time_ms"], independent["task_completion_time_ms"])

    def test_environment_uses_device_duration_not_model_estimate(self):
        class LongEstimateClient(DryRunClient):
            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                if decision["actions"]:
                    decision["actions"][0]["estimated_duration_ms"] = 600000
                return decision

        episode = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-003.json")
        trace, _ = run_closed_loop_episode(
            episode, LongEstimateClient(), "CentralSingleAgent", INSTRUCTIONS, synthetic_latency=True
        )
        window = next(event for event in trace["events"] if event.get("target") == "window")
        self.assertEqual(2000, window["duration_ms"])
        self.assertEqual(600000, window["proposed_duration_ms"])

    def test_direct_conflict_boundary_depends_on_specialist_visibility(self):
        seed = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-002.json")
        variants = direct_conflict_variants(seed)
        visible = next(item for item in variants if item["variant"] == {
            "family": "direct_device_conflict", "energy_visibility": "policy_visible", "second_task_gap_ms": 0,
        })
        local = next(item for item in variants if item["variant"] == {
            "family": "direct_device_conflict", "energy_visibility": "local_only", "second_task_gap_ms": 0,
        })

        _, independent_visible = self.run_variant(visible, "IndependentMultiAgent")
        _, independent_local = self.run_variant(local, "IndependentMultiAgent")
        _, coordinated_local = self.run_variant(local, "RuleCoordinator")

        self.assertTrue(independent_visible["process_valid_success"])
        self.assertEqual(0, independent_visible["conflict_counts"]["C1"])
        self.assertFalse(independent_local["process_valid_success"])
        self.assertEqual(1, independent_local["conflict_counts"]["C1"])
        self.assertTrue(coordinated_local["process_valid_success"])
        self.assertEqual(0, coordinated_local["conflict_counts"]["C1"])

    def test_rule_coordinator_holds_low_priority_action_for_pending_high_priority_task(self):
        class EnergyReturnsFirstClient(DryRunClient):
            def decide(self, agent_request, instructions=""):
                decision = super().decide(agent_request, instructions)
                acting_role = agent_request["task"]["agent_id"]
                self.last_latency_ms = 900 if acting_role == "ComfortAgent" else 100
                return decision

        seed = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-002.json")
        episode = next(
            item for item in direct_conflict_variants(seed)
            if item["variant"]["energy_visibility"] == "local_only"
            and item["variant"]["second_task_gap_ms"] == 0
        )
        _, independent = run_closed_loop_episode(
            episode, EnergyReturnsFirstClient(), "IndependentMultiAgent", INSTRUCTIONS, synthetic_latency=False
        )
        trace, coordinated = run_closed_loop_episode(
            episode, EnergyReturnsFirstClient(), "RuleCoordinator", INSTRUCTIONS, synthetic_latency=False
        )

        self.assertEqual(1, independent["conflict_counts"]["C1"])
        self.assertEqual(0, coordinated["conflict_counts"]["C1"])
        self.assertTrue(any(
            event.get("reason") == "priority_resolution"
            for event in trace["events"] if event["type"] == "coordination_decision"
        ))

    def test_stale_action_boundary_depends_on_event_timing(self):
        seed = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-004.json")
        variants = stale_action_variants(seed)
        before_effect = next(item for item in variants if item["variant"]["resident_enter_at_ms"] == 1800)
        after_effect = next(item for item in variants if item["variant"]["resident_enter_at_ms"] == 2200)

        _, independent_before = self.run_variant(before_effect, "IndependentMultiAgent")
        _, coordinated_before = self.run_variant(before_effect, "RuleCoordinator")
        _, independent_after = self.run_variant(after_effect, "IndependentMultiAgent")
        _, coordinated_after = self.run_variant(after_effect, "RuleCoordinator")

        self.assertFalse(independent_before["process_valid_success"])
        self.assertEqual(1, independent_before["conflict_counts"]["C4"])
        self.assertTrue(coordinated_before["process_valid_success"])
        self.assertTrue(independent_after["process_valid_success"])
        self.assertTrue(coordinated_after["process_valid_success"])

    def test_indirect_conflict_boundary_depends_on_action_overlap(self):
        seed = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-003.json")
        variants = indirect_conflict_variants(seed)
        boundary_conflict = next(item for item in variants if item["variant"]["second_task_gap_ms"] == 1000)
        boundary_safe = next(item for item in variants if item["variant"]["second_task_gap_ms"] == 1500)

        _, independent_conflict = self.run_variant(boundary_conflict, "IndependentMultiAgent")
        _, rules_conflict = self.run_variant(boundary_conflict, "RuleCoordinator")
        _, constrained_safe = self.run_variant(boundary_conflict, "ConstraintCoordinator")
        _, central_safe = self.run_variant(boundary_conflict, "CentralSingleAgent")
        _, independent_safe = self.run_variant(boundary_safe, "IndependentMultiAgent")
        _, constrained_boundary_safe = self.run_variant(boundary_safe, "ConstraintCoordinator")

        self.assertEqual(1, independent_conflict["conflict_counts"]["C2"])
        self.assertEqual(1, rules_conflict["conflict_counts"]["C2"])
        self.assertEqual(0, constrained_safe["conflict_counts"]["C2"])
        self.assertEqual(0, central_safe["conflict_counts"]["C2"])
        self.assertEqual(0, independent_safe["conflict_counts"]["C2"])
        self.assertEqual(
            independent_safe["task_completion_time_ms"],
            constrained_boundary_safe["task_completion_time_ms"],
        )
        self.assertGreater(
            constrained_safe["task_completion_time_ms"],
            independent_conflict["task_completion_time_ms"],
        )

    def test_resource_capacity_boundary_depends_on_parallel_power(self):
        seed = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-001.json")
        variants = resource_capacity_variants(seed)
        constrained = next(item for item in variants if item["variant"]["capacity_kw"] == 1.21)
        sufficient = next(item for item in variants if item["variant"]["capacity_kw"] == 1.23)

        _, independent_conflict = self.run_variant(constrained, "IndependentMultiAgent")
        _, rules_conflict = self.run_variant(constrained, "RuleCoordinator")
        _, constrained_safe = self.run_variant(constrained, "ConstraintCoordinator")
        _, central_safe = self.run_variant(constrained, "CentralSingleAgent")
        _, independent_safe = self.run_variant(sufficient, "IndependentMultiAgent")
        _, constrained_capacity_safe = self.run_variant(sufficient, "ConstraintCoordinator")

        self.assertEqual(1, independent_conflict["conflict_counts"]["C3"])
        self.assertEqual(1, rules_conflict["conflict_counts"]["C3"])
        self.assertEqual(0, constrained_safe["conflict_counts"]["C3"])
        self.assertEqual(0, central_safe["conflict_counts"]["C3"])
        self.assertEqual(0, independent_safe["conflict_counts"]["C3"])
        self.assertEqual(
            independent_safe["task_completion_time_ms"],
            constrained_capacity_safe["task_completion_time_ms"],
        )
        self.assertGreater(
            constrained_safe["task_completion_time_ms"],
            independent_conflict["task_completion_time_ms"],
        )

    def test_first_candidate_templates_use_episode_grounding(self):
        """New device/environment tasks must exercise the generic grounding path."""
        for episode_id in ("HC-M02", "HC-M03", "HC-M07", "HC-M08"):
            with self.subTest(episode_id=episode_id):
                episode = load_json(BENCH_ROOT / "data" / "candidates" / f"{episode_id}.json")
                _, independent = run_closed_loop_episode(
                    episode, DryRunClient(), "IndependentMultiAgent", INSTRUCTIONS, synthetic_latency=True
                )
                _, constrained = run_closed_loop_episode(
                    episode, DryRunClient(), "ConstraintCoordinator", INSTRUCTIONS, synthetic_latency=True
                )
                self.assertEqual(1.0, independent["task_service_rate"])
                self.assertEqual(0, sum(constrained["conflict_counts"].values()))
                self.assertTrue(constrained["final_goal_success"])
                self.assertTrue(constrained["process_valid_success"])
        for episode_id in ("HC-M02", "HC-M03"):
            episode = load_json(BENCH_ROOT / "data" / "candidates" / f"{episode_id}.json")
            _, independent = run_closed_loop_episode(
                episode, DryRunClient(), "IndependentMultiAgent", INSTRUCTIONS, synthetic_latency=True
            )
            self.assertEqual(1, independent["conflict_counts"]["C1"])
        for episode_id in ("HC-M07", "HC-M08"):
            episode = load_json(BENCH_ROOT / "data" / "candidates" / f"{episode_id}.json")
            _, independent = run_closed_loop_episode(
                episode, DryRunClient(), "IndependentMultiAgent", INSTRUCTIONS, synthetic_latency=True
            )
            self.assertEqual(1, independent["conflict_counts"]["C2"])

    def test_second_candidate_templates_cover_capacity_and_stale_state(self):
        for episode_id in ("HC-M12", "HC-M13"):
            with self.subTest(episode_id=episode_id):
                episode = load_json(BENCH_ROOT / "data" / "candidates" / f"{episode_id}.json")
                _, independent = run_closed_loop_episode(
                    episode, DryRunClient(), "IndependentMultiAgent", INSTRUCTIONS, synthetic_latency=True
                )
                _, constrained = run_closed_loop_episode(
                    episode, DryRunClient(), "ConstraintCoordinator", INSTRUCTIONS, synthetic_latency=True
                )
                self.assertEqual(1, independent["conflict_counts"]["C3"])
                self.assertFalse(independent["process_valid_success"])
                self.assertEqual(0, sum(constrained["conflict_counts"].values()))
                self.assertTrue(constrained["process_valid_success"])
                self.assertEqual(1.0, constrained["task_service_rate"])
        for episode_id in ("HC-M17", "HC-M20"):
            with self.subTest(episode_id=episode_id):
                episode = load_json(BENCH_ROOT / "data" / "candidates" / f"{episode_id}.json")
                _, independent = run_closed_loop_episode(
                    episode, DryRunClient(), "IndependentMultiAgent", INSTRUCTIONS, synthetic_latency=True
                )
                _, constrained = run_closed_loop_episode(
                    episode, DryRunClient(), "ConstraintCoordinator", INSTRUCTIONS, synthetic_latency=True
                )
                self.assertEqual(1, independent["conflict_counts"]["C4"])
                self.assertFalse(independent["process_valid_success"])
                self.assertEqual(0, sum(constrained["conflict_counts"].values()))
                self.assertTrue(constrained["process_valid_success"])


if __name__ == "__main__":
    unittest.main()
