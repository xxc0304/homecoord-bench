"""Synthetic sensitivity of EV/water coordination to published power bounds.

Historical DeepSeek call durations are reused only as logical proposal arrivals.
The actions, capacity and deadlines are uncalibrated assumptions. No API call.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_ev_water_event_gate import RecordedLatencyScriptedActions
from probe_physical_capacity_v2 import make_episode
from runtime.event_simulator import run_event_simulation

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "physical_capacity_v2.json"
OUTPUT = ROOT / "results" / "ev_water_information_boundary_20260927.json"
DELAYS_MS = (0, 300, 800)
BOUND_PROFILES: dict[str, dict[str, float] | None] = {
    "accurate": {"charge_ev": 4.0, "heat_water": 3.0},
    "ev_understated": {"charge_ev": 2.0, "heat_water": 3.0},
    "ev_overstated": {"charge_ev": 5.0, "heat_water": 3.0},
    "missing": None,
}
POLICIES = ("ConstraintCoordinator", "DeadlineAwareCoordinator",
            "CapacityAwareDeadlineCoordinator")


def run_pilot(output: Path = OUTPUT) -> dict[str, Any]:
    source_bytes = SOURCE.read_bytes()
    source = json.loads(source_bytes)
    rows: list[dict[str, Any]] = []
    for source_row in source["rows"]:
        records = source_row.get("model_records", {})
        if set(records) != {"charge_ev", "heat_water"}:
            continue
        latencies = {task_id: int(record["logical_latency_ms"])
                     for task_id, record in records.items()}
        for condition in ("conflict", "control"):
            base = make_episode(condition)
            for policy in POLICIES:
                profiles = BOUND_PROFILES if policy == "CapacityAwareDeadlineCoordinator" else {"not_used": None}
                for profile, bounds in profiles.items():
                    for delay in DELAYS_MS:
                        episode = deepcopy(base)
                        if bounds is not None:
                            episode["home"]["resources"]["task_power_bounds_kw"] = deepcopy(bounds)
                        trace, result = run_event_simulation(
                            episode, RecordedLatencyScriptedActions(latencies),
                            policy, "", coordination_delay_ms=delay,
                            shared_safety_gate=True,
                        )
                        rows.append({
                            "source_repetition": source_row["repetition"],
                            "condition": condition,
                            "capacity_kw": episode["home"]["resources"]["max_power_kw"],
                            "policy": policy,
                            "bound_profile": profile,
                            "public_task_power_bounds_kw": bounds,
                            "synthetic_coordination_delay_ms": delay,
                            "proposal_latency_by_task_ms": latencies,
                            "first_proposal_returned_task": next(
                                event["task_id"] for event in trace["events"]
                                if event["type"] == "proposal_returned"
                            ),
                            "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                            "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                            "task_deadline_met": result["task_deadline_met"],
                            "all_deadlines_met": result["all_deadlines_met"],
                            "all_tasks_served": all(result["task_service"].values()),
                            "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                            "conflict_count": sum(result["conflict_counts"].values()),
                        })
    payload = {
        "schema_version": "ev-water-information-boundary-0.1",
        "status": "uncalibrated_synthetic_parameter_grid_same_task_template",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "historical_model_calls_are_sequential_logical_arrivals": True,
        "bound_profiles": BOUND_PROFILES,
        "synthetic_coordination_delays_ms": DELAYS_MS,
        "actual_rule_wall_clock_measured": False,
        "same_shared_safety_gate_for_all_policies": True,
        "new_api_calls": 0,
        "real_devices": 0,
        "rows": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run_pilot()
    print(json.dumps({"cells": len(result["rows"]), "output": str(OUTPUT)},
                     ensure_ascii=False))
