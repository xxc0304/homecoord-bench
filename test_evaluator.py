import json
import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import evaluate, load_json, validate_episode_shape  # noqa: E402
from run_scripted_baselines import run  # noqa: E402


class SeedEpisodeTests(unittest.TestCase):
    def case(self, episode_id: str, trace_name: str):
        episode = load_json(BENCH_ROOT / "data" / "seeds" / f"{episode_id}.json")
        trace = load_json(BENCH_ROOT / "traces" / trace_name)
        return evaluate(episode, trace)

    def test_all_episodes_have_minimum_shape(self):
        for path in (BENCH_ROOT / "data" / "seeds").glob("*.json"):
            with self.subTest(path=path.name):
                self.assertEqual([], validate_episode_shape(load_json(path)))

    def test_safe_parallel_trace_exposes_serialization_cost(self):
        parallel = self.case("HC-SEED-001", "HC-SEED-001.parallel.json")
        serial = self.case("HC-SEED-001", "HC-SEED-001.serial.json")
        self.assertTrue(parallel["process_valid_success"])
        self.assertTrue(serial["process_valid_success"])
        self.assertLess(parallel["task_completion_time_ms"], serial["task_completion_time_ms"])
        self.assertLess(parallel["first_effective_action_latency_ms"], serial["first_effective_action_latency_ms"])

    def test_direct_conflict_is_detected(self):
        good = self.case("HC-SEED-002", "HC-SEED-002.coordinated.json")
        bad = self.case("HC-SEED-002", "HC-SEED-002.conflict.json")
        self.assertTrue(good["process_valid_success"])
        self.assertEqual(0, good["conflict_counts"]["C1"])
        self.assertGreaterEqual(bad["conflict_counts"]["C1"], 1)
        self.assertFalse(bad["process_valid_success"])

    def test_task_service_exposes_safety_utility_tradeoff(self):
        coordinated = self.case("HC-SEED-002", "HC-SEED-002.coordinated.json")
        conflicting = self.case("HC-SEED-002", "HC-SEED-002.conflict.json")
        self.assertEqual({"comfort": True, "energy": False}, coordinated["task_service"])
        self.assertEqual(0.5, coordinated["task_service_rate"])
        self.assertEqual({"comfort": True, "energy": True}, conflicting["task_service"])
        self.assertEqual(1.0, conflicting["task_service_rate"])

    def test_indirect_conflict_is_detected(self):
        good = self.case("HC-SEED-003", "HC-SEED-003.sequenced.json")
        bad = self.case("HC-SEED-003", "HC-SEED-003.overlap.json")
        self.assertTrue(good["process_valid_success"])
        self.assertEqual(0, good["conflict_counts"]["C2"])
        self.assertEqual(1, bad["conflict_counts"]["C2"])
        self.assertFalse(bad["process_valid_success"])

    def test_stale_action_and_safety_violation_are_detected(self):
        good = self.case("HC-SEED-004", "HC-SEED-004.revalidated.json")
        bad = self.case("HC-SEED-004", "HC-SEED-004.stale.json")
        self.assertTrue(good["process_valid_success"])
        self.assertEqual(0, good["stale_action_count"])
        self.assertEqual(1, bad["stale_action_count"])
        self.assertEqual(1, bad["constraint_violation_count"])
        self.assertTrue(bad["final_goal_success"])
        self.assertFalse(bad["process_valid_success"])

    def test_coordination_decision_is_not_counted_as_effective_action(self):
        result = self.case("HC-SEED-002", "HC-SEED-002.coordinated.json")
        self.assertEqual(250, result["coordination_decision_latency_ms"])
        self.assertEqual(700, result["first_effective_action_latency_ms"])

    def test_multiple_coordination_decisions_are_supported(self):
        episode = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-001.json")
        trace = load_json(BENCH_ROOT / "traces" / "HC-SEED-001.parallel.json")
        trace["events"].insert(1, {"type": "coordination_decision", "timestamp_ms": 90, "decision": "accept_second"})
        result = evaluate(episode, trace)
        self.assertEqual(80, result["coordination_decision_latency_ms"])
        self.assertTrue(result["process_valid_success"])

    def test_scripted_baselines_have_expected_discriminability(self):
        summary = run()["summary"]
        central = summary["CentralSingleAgent"]
        independent = summary["IndependentMultiAgent"]
        rules = summary["RuleCoordinator"]
        self.assertEqual(1.0, central["process_valid_success_rate"])
        self.assertLess(independent["process_valid_success_rate"], rules["process_valid_success_rate"])
        self.assertLess(rules["process_valid_success_rate"], central["process_valid_success_rate"])
        self.assertGreater(independent["total_conflicts"], 0)


if __name__ == "__main__":
    unittest.main()
