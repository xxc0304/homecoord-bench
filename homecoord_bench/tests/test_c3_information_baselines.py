"""Information and service contracts for stronger admission baselines."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_information_baselines_20260930 import adapt, contracts
from probe_c3_scale_release_20260930 import build, templates
from probe_c3_structural_generalization import ScriptedProposalClient
from runtime.event_simulator import run_event_simulation


class InformationBaselineTests(unittest.TestCase):
    def episode(self, name="N2-1"):
        return build(name, templates()[name], "tight", "urgent_late", 1.6)

    def execute(self, episode, label):
        changed, policy = adapt(episode, label)
        latencies = {t["task_id"]: 800 + i * 200 for i, t in enumerate(episode["task_stream"])}
        return run_event_simulation(changed, ScriptedProposalClient(latencies), policy,
                                    "", shared_safety_gate=True)

    def test_costs_come_from_advertised_tools_not_hidden_template(self):
        original = self.episode()
        poisoned = deepcopy(original)
        for task in poisoned["task_stream"]:
            task["action_template"].update({"duration_ms": 123, "power_kw": 999})
        self.assertEqual(contracts(original), contracts(poisoned))
        adapted, _ = adapt(poisoned, "ReleasedFeasibilityFallback")
        for task in adapted["task_stream"]:
            self.assertEqual(contracts(original)[task["task_id"]]["duration_ms"], task["action_template"]["duration_ms"])
            self.assertEqual(contracts(original)[task["task_id"]]["power_kw"], task["action_template"]["power_kw"])

    def test_fallback_serves_late_work_without_bypassing_safety(self):
        strict_trace, strict = self.execute(self.episode(), "ReleasedFeasibilityStrict")
        trace, fallback = self.execute(self.episode(), "ReleasedFeasibilityFallback")
        self.assertFalse(all(strict["task_service"].values()))
        self.assertTrue(all(fallback["task_service"].values()))
        self.assertFalse(fallback["all_deadlines_met"])
        self.assertTrue(any(e["type"] == "feasibility_fallback" for e in trace["events"]))
        self.assertEqual(0, fallback["state_constraint_violation_duration_ms"])
        starts = [e for e in trace["events"] if e["type"] == "action_started"]
        self.assertEqual(2, len(starts))
        self.assertGreater(starts[1]["timestamp_ms"], starts[0]["timestamp_ms"])

    def test_future_metadata_cannot_change_released_only_prefix(self):
        episode = self.episode("N5-1")
        absent = deepcopy(episode)
        future = next(t for t in absent["task_stream"] if t["release_at_ms"] > 0)
        absent["task_stream"].remove(future)
        absent["action_grounding"] = [g for g in absent["action_grounding"] if g["task_id"] != future["task_id"]]
        absent["tool_catalog"] = [g for g in absent["tool_catalog"] if g["agent_id"] != future["agent_id"]]
        absent["agents"] = [g for g in absent["agents"] if g["agent_id"] != future["agent_id"]]
        absent["home"]["resources"]["task_power_bounds_kw"].pop(future["task_id"])
        absent["goals"] = [g for g in absent["goals"] if g["path"] != "services." + future["required_action"]["target"]]
        for label in ("ReleasedFeasibilityStrict", "ReleasedFeasibilityFallback"):
            traces = [self.execute(e, label)[0] for e in (episode, absent)]
            prefixes = [[(x["task_id"], x["timestamp_ms"], x["operation"]) for x in t["events"]
                         if x["type"] == "action_started" and x["timestamp_ms"] < 60000] for t in traces]
            self.assertEqual(prefixes[0], prefixes[1], label)

    def test_perfect_announcement_is_explicit_extra_information(self):
        episode = self.episode()
        ordinary, _ = adapt(episode, "ReleasedFeasibilityFallback")
        announced, policy = adapt(episode, "PerfectAnnouncementReserve")
        self.assertNotIn("potential_urgent", ordinary["simulation"])
        self.assertEqual("RobustReserveCoordinator", policy)
        self.assertEqual([60000], announced["simulation"]["potential_urgent"]["possible_release_ms"])
        _, result = self.execute(episode, "PerfectAnnouncementReserve")
        self.assertTrue(result["all_deadlines_met"])


if __name__ == "__main__":
    unittest.main()
