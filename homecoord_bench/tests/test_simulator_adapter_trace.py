"""Tests for the offline simulator-adapter trace contract auditor."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from audit_simulator_adapter_trace import audit_paths  # noqa: E402


def make_trace(run_id: str, *, final_digest: str = "final") -> list[dict]:
    metadata = {
        "schema_version": "simulator-adapter-trace-0.1",
        "run_id": run_id,
        "scenario_id": "hvac-opposite-actions",
        "schedule_id": "cool-then-off",
        "backend_revision": "test-revision",
        "random_seed": 7,
        "tick_ms": 1000,
        "expected_proposal_order": ["p-cool", "p-off"],
    }
    events = []

    def add(event_type: str, tick: int, **values: object) -> None:
        events.append({
            **metadata,
            "seq": len(events),
            "event_type": event_type,
            "homecoord_tick": tick,
            "backend_tick": tick,
            **values,
        })

    add("reset", 0, state_digest="initial")
    add("state_snapshot", 0, state_digest="initial")
    add("proposal_scheduled", 0, proposal_id="p-cool", agent_id="ComfortAgent", task_id="cool")
    add("command_submitted", 0, proposal_id="p-cool", command_bundle_id="b-cool", command_id="c-on", command_order=0)
    add("command_result", 0, proposal_id="p-cool", command_id="c-on", status="completed", execution_order=0, order_evidence="state_observation")
    add("command_submitted", 0, proposal_id="p-cool", command_bundle_id="b-cool", command_id="c-mode", command_order=1)
    add("command_result", 0, proposal_id="p-cool", command_id="c-mode", status="completed", execution_order=1, order_evidence="backend_ack")
    add("proposal_scheduled", 0, proposal_id="p-off", agent_id="EnergyAgent", task_id="off")
    add("command_submitted", 0, proposal_id="p-off", command_bundle_id="b-off", command_id="c-off", command_order=0)
    add("command_result", 0, proposal_id="p-off", command_id="c-off", status="completed", execution_order=2, order_evidence="state_observation")
    add("tick_advanced", 1)
    add("state_snapshot", 1, state_digest="middle")
    add("tick_advanced", 2)
    add("state_snapshot", 2, state_digest=final_digest, is_final=True)
    add("run_finished", 2, state_digest=final_digest)
    return events


class SimulatorAdapterTraceTests(unittest.TestCase):
    def audit(self, traces: list[list[dict]]) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for index, trace in enumerate(traces):
                path = Path(temp_dir) / f"run-{index}.jsonl"
                path.write_text(
                    "\n".join(json.dumps(event) for event in trace) + "\n",
                    encoding="utf-8",
                )
                paths.append(path)
            return audit_paths(paths)

    def test_valid_replays_preserve_bundle_lineage_and_order(self):
        report = self.audit([make_trace("r1"), make_trace("r2")])
        self.assertEqual(2, report["valid_count"])
        self.assertEqual(0, report["invalid_count"])
        self.assertEqual(1, report["deterministic_replay_group_count"])
        self.assertEqual(["p-cool", "p-off"], report["records"][0]["observed_proposal_execution_order"])
        self.assertEqual(3, report["records"][0]["command_count"])

    def test_clock_regression_and_unlinked_command_are_rejected(self):
        trace = make_trace("r1")
        command = next(event for event in trace if event["event_type"] == "command_submitted")
        command["proposal_id"] = "missing-proposal"
        tick = next(event for event in trace if event["event_type"] == "tick_advanced")
        tick["homecoord_tick"] = -1
        report = self.audit([trace])
        self.assertEqual(0, report["valid_count"])
        self.assertTrue(any("unknown proposal_id" in item["error"] for item in report["errors"]))
        self.assertTrue(any("HomeCoord virtual clock" in item["error"] or "homecoord_tick must" in item["error"] for item in report["errors"]))

    def test_execution_order_must_be_observable_and_match_schedule(self):
        trace = make_trace("r1")
        result = [event for event in trace if event["event_type"] == "command_result"][-1]
        result["execution_order"] = 0
        result["order_evidence"] = None
        report = self.audit([trace])
        self.assertEqual(0, report["valid_count"])
        self.assertTrue(any("execution_order requires" in item["error"] for item in report["errors"]))

        trace = make_trace("r2")
        result = [event for event in trace if event["event_type"] == "command_result"][-1]
        result["execution_order"] = 0
        report = self.audit([trace])
        self.assertTrue(any("duplicate execution_order" in item["error"] for item in report["errors"]))

    def test_replay_state_mismatch_is_reported_across_runs(self):
        first = make_trace("r1")
        second = make_trace("r2", final_digest="different-final")
        report = self.audit([first, second])
        self.assertEqual(0, report["deterministic_replay_group_count"])
        self.assertTrue(any("replay mismatch" in item["error"] for item in report["errors"]))

    def test_malformed_unhashable_fields_are_reported_without_crashing(self):
        trace = make_trace("r1")
        trace[0]["event_type"] = []
        proposal = next(event for event in trace if event.get("event_type") == "proposal_scheduled")
        proposal["proposal_id"] = ["bad-id"]
        trace[0]["scenario_id"] = ["malformed"]
        report = self.audit([trace])
        self.assertEqual(0, report["valid_count"])
        self.assertGreater(len(report["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
