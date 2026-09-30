"""Protect release clocks and the no-future-information comparison."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_scale_release_20260930 import build, templates, POLICIES
from probe_c3_structural_generalization import ScriptedProposalClient
from runtime.event_simulator import run_event_simulation


class ScaleReleaseTests(unittest.TestCase):
    def test_staggering_preserves_each_task_response_window(self):
        specs = templates()["N5-1"]
        for deadline in ("tight", "loose"):
            together = build("N5-1", specs, deadline, "together", 1.6)
            for pattern in ("urgent_late", "urgent_first"):
                shifted = build("N5-1", specs, deadline, pattern, 1.6)
                for a, b in zip(together["task_stream"], shifted["task_stream"]):
                    self.assertEqual(a["completion_deadline_ms"] - a["release_at_ms"],
                                     b["completion_deadline_ms"] - b["release_at_ms"])
                    self.assertEqual(a["goal"], b["goal"])

    def test_hidden_future_task_does_not_change_before_release_actions(self):
        episode = build("N5-1", templates()["N5-1"], "tight", "urgent_late", 1.6)
        absent = deepcopy(episode)
        future = next(t for t in absent["task_stream"] if t["release_at_ms"] > 0)
        absent["task_stream"].remove(future)
        absent["action_grounding"] = [g for g in absent["action_grounding"] if g["task_id"] != future["task_id"]]
        absent["tool_catalog"] = [c for c in absent["tool_catalog"] if c["agent_id"] != future["agent_id"]]
        absent["agents"] = [a for a in absent["agents"] if a["agent_id"] != future["agent_id"]]
        absent["home"]["resources"]["task_power_bounds_kw"].pop(future["task_id"])
        target = future["required_action"]["target"]
        absent["goals"] = [g for g in absent["goals"] if g["path"] != f"services.{target}"]
        latencies = {t["task_id"]: 800 + i * 200 for i, t in enumerate(episode["task_stream"])}
        for policy in POLICIES:
            traces = [run_event_simulation(e, ScriptedProposalClient(latencies), policy, "",
                                           shared_safety_gate=True)[0] for e in (episode, absent)]
            prefixes = [[(x["task_id"], x["timestamp_ms"], x["operation"])
                         for x in trace["events"] if x["type"] == "action_started"
                         and x["timestamp_ms"] < future["release_at_ms"]] for trace in traces]
            self.assertEqual(prefixes[0], prefixes[1], policy)
            self.assertTrue(prefixes[0], policy)

    def test_proposal_latency_is_relative_to_its_own_release(self):
        episode = build("N4-1", templates()["N4-1"], "tight", "urgent_late", 1.6)
        latencies = {t["task_id"]: 800 + i * 200 for i, t in enumerate(episode["task_stream"])}
        trace, _ = run_event_simulation(episode, ScriptedProposalClient(latencies),
                                         "GateRetryRule", "", shared_safety_gate=True)
        returns = {e["task_id"]: e["timestamp_ms"] for e in trace["events"] if e["type"] == "proposal_returned"}
        for task in episode["task_stream"]:
            self.assertEqual(task["release_at_ms"] + latencies[task["task_id"]], returns[task["task_id"]])


if __name__ == "__main__":
    unittest.main()
