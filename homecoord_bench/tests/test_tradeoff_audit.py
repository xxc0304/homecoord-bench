import sys
import unittest
from copy import deepcopy
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from audit_candidate_tradeoffs import evaluate_case, safe_control  # noqa: E402
from evaluate import load_json  # noqa: E402
from probe_capacity_deadline import make_probe, priority_first_witness, score  # noqa: E402
from run_capacity_deadline_matrix import run as run_deadline_matrix  # noqa: E402
from run_online_deadline_baselines import online_schedule, run as run_online_baselines  # noqa: E402
from run_protocol_pilot import INSTRUCTIONS  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.execution import run_closed_loop_episode  # noqa: E402


class TradeoffDesignTests(unittest.TestCase):
    def test_online_rules_solve_current_tight_cases_without_future_proposals(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            result = run_online_baselines(Path(directory) / "online.json")
        for policy in ("WaitReleasedPriority", "WaitReleasedEDF", "WaitReleasedPriorityCapacityAware"):
            self.assertEqual(result["summary"][f"tight_conflicting.{policy}"]["safe_and_on_time"], 5)
        self.assertEqual(result["summary"]["tight_conflicting.ImmediateFIFO"]["safe_and_on_time"], 0)

    def test_capacity_aware_wait_does_not_wait_when_both_actions_fit(self):
        from run_capacity_deadline_matrix import make_scenarios

        source = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M13.json")
        scenarios, _ = make_scenarios(source)
        safe = next(episode for name, episode in scenarios if name == "safe_capacity")
        trace, result = online_schedule(safe, "WaitReleasedPriorityCapacityAware")
        self.assertTrue(result["timely_process_valid_success"])
        self.assertFalse(any(
            event.get("decision") == "wait_for_released_task"
            for event in trace["events"]
        ))

    def test_unreleased_urgent_task_cannot_be_predicted_by_online_rule(self):
        from run_capacity_deadline_matrix import make_scenarios

        source = load_json(BENCH_ROOT / "data" / "candidates" / "HC-M13.json")
        scenarios, info = make_scenarios(source)
        early = scenarios[0][1]
        late = deepcopy(early)
        late["episode_id"] += ".late_release"
        high = next(task for task in late["task_stream"] if task["task_id"] == info["high_task_id"])
        high["release_at_ms"] = 700  # low-priority proposal was already returned at 600 ms
        high["completion_deadline_ms"] = 8500  # feasible if high could start on arrival
        _, early_result = online_schedule(early, "WaitReleasedEDF")
        late_trace, late_result = online_schedule(late, "WaitReleasedEDF")
        self.assertTrue(early_result["timely_process_valid_success"])
        self.assertEqual(early_result["task_action_finish_time_ms"][info["high_task_id"]], 6800)
        self.assertTrue(late_result["process_valid_success"])
        self.assertFalse(late_result["timely_process_valid_success"])
        self.assertGreater(late_result["task_action_finish_time_ms"][info["high_task_id"]], 8500)
        self.assertFalse(any(event.get("decision") == "wait_for_released_task" for event in late_trace["events"]))

    def test_capacity_deadline_controls_separate_safety_and_timeliness(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            result = run_deadline_matrix(Path(directory) / "matrix.json")
        summary = result["summary"]
        self.assertEqual(summary["source_templates"], 5)
        self.assertEqual(summary["tight_fifo_process_valid"], 5)
        self.assertEqual(summary["tight_fifo_deadlines_met"], 0)
        self.assertEqual(summary["tight_priority_witness_process_valid"], 5)
        self.assertEqual(summary["tight_priority_witness_deadlines_met"], 5)
        self.assertEqual(summary["safe_capacity_independent_process_valid"], 5)
        self.assertEqual(summary["safe_capacity_fifo_deadlines_met"], 5)
        self.assertEqual(summary["relaxed_deadline_fifo_deadlines_met"], 5)

    def test_indirect_and_capacity_controls_change_failure_to_safe_parallelism(self):
        for episode_id in ("HC-M06", "HC-M13"):
            with self.subTest(episode=episode_id):
                original = load_json(BENCH_ROOT / "data" / "candidates" / f"{episode_id}.json")
                paired, _ = safe_control(original)
                before = evaluate_case(original)
                after = evaluate_case(paired)
                self.assertFalse(before["IndependentMultiAgent"]["process_valid_success"])
                self.assertTrue(after["IndependentMultiAgent"]["process_valid_success"])
                self.assertTrue(after["ConstraintCoordinator"]["process_valid_success"])
                self.assertEqual(
                    after["IndependentMultiAgent"]["first_action_ms"],
                    after["ConstraintCoordinator"]["first_action_ms"],
                )
                self.assertEqual(
                    after["IndependentMultiAgent"]["completion_ms"],
                    after["ConstraintCoordinator"]["completion_ms"],
                )

    def test_priority_first_schedule_is_safe_and_meets_tight_deadline(self):
        episode = make_probe(capacity_kw=6.0, deadline_ms=9000)
        fifo_trace, fifo_result = run_closed_loop_episode(
            episode, DryRunClient(), "ConstraintCoordinator", INSTRUCTIONS, synthetic_latency=True
        )
        witness_trace, witness_result = priority_first_witness(episode, fifo_trace)
        fifo = score(episode, fifo_trace, fifo_result)
        witness = score(episode, witness_trace, witness_result)
        self.assertTrue(fifo["process_valid_success"])
        self.assertTrue(witness["process_valid_success"])
        self.assertFalse(fifo["charge_ev_deadline_met"])
        self.assertTrue(witness["charge_ev_deadline_met"])
        self.assertGreater(witness["first_effective_action_ms"], fifo["first_effective_action_ms"])


if __name__ == "__main__":
    unittest.main()
