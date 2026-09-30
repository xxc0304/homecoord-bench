"""Replay logged proposal latencies through the common event/safety runtime.

The two actions are scripted to be identical across policies. Historical
DeepSeek latencies are reused without calling the API. Device power, work,
capacity and deadlines remain uncalibrated stress-test assumptions.
"""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_physical_capacity_v2 import make_episode
from runtime.dry_run import DryRunClient
from runtime.event_simulator import run_event_simulation

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "physical_capacity_v2.json"
OUTPUT = ROOT / "results" / "ev_water_common_gate_event_replay_20260927.json"
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
    "CentralSingleAgent",
)


class RecordedLatencyScriptedActions(DryRunClient):
    def __init__(self, latencies_by_task_ms: dict[str, int]) -> None:
        self.latencies_by_task_ms = latencies_by_task_ms

    def decide(self, request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        decision = super().decide(request, instructions)
        self.last_latency_ms = self.latencies_by_task_ms[request["task"]["task_id"]]
        return decision


def run_pilot() -> dict[str, Any]:
    source_bytes = SOURCE.read_bytes()
    previous = json.loads(source_bytes)
    episodes = {condition: make_episode(condition) for condition in ("conflict", "control")}
    for episode in episodes.values():
        episode["home"]["resources"]["task_power_bounds_kw"] = {
            "charge_ev": 4.0, "heat_water": 3.0,
        }
    rows = []
    for source_row in previous["rows"]:
        records = source_row.get("model_records", {})
        if set(records) != {"charge_ev", "heat_water"}:
            continue
        latencies = {task_id: int(record["logical_latency_ms"])
                     for task_id, record in records.items()}
        for condition, episode in episodes.items():
            for policy in POLICIES:
                trace, result = run_event_simulation(
                    deepcopy(episode), RecordedLatencyScriptedActions(latencies),
                    policy, "", shared_safety_gate=True,
                )
                rows.append({
                    "source_repetition": source_row["repetition"],
                    "condition": condition,
                    "policy": policy,
                    "proposal_latency_by_task_ms": latencies,
                    "first_proposal_returned_task": next(
                        event["task_id"] for event in trace["events"]
                        if event["type"] == "proposal_returned"
                    ),
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                    "task_deadline_met": result["task_deadline_met"],
                    "all_deadlines_met": result["all_deadlines_met"],
                    "task_service": result["task_service"],
                    "all_tasks_served": all(result["task_service"].values()),
                    "conflict_counts": result["conflict_counts"],
                    "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                    "rejection_reasons": [event["reason"] for event in trace["events"]
                                          if event["type"] == "action_rejected"],
                })
    payload = {
        "schema_version": "ev-water-common-gate-event-replay-0.1",
        "status": "uncalibrated_physical_assumptions_scripted_actions_logged_model_latencies",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_model": previous.get("model"),
        "physical_assumptions": episodes["conflict"]["physical_assumptions"],
        "same_shared_safety_gate_for_all_policies": True,
        "public_task_power_bounds_kw": {"charge_ev": 4.0, "heat_water": 3.0},
        "new_api_calls": 0,
        "real_devices": 0,
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = run_pilot()
    print(json.dumps({"rows": len(report["rows"]), "output": str(OUTPUT)},
                     ensure_ascii=False, indent=2))
