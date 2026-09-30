"""Probe coordination value across capacity and deadline-slack regimes.

This is a controlled parameter sweep of one synthetic EV/water task template,
not a collection of independent household examples.
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
OUTPUT = ROOT / "results" / "ev_water_deadline_boundary_20260927.json"
HOUR_MS = 3_600_000
CAPACITIES_KW = (6.0, 7.0, 7.2)
DEADLINE_PROFILES_MS = {
    "ev_urgent": {"charge_ev": 5.1 * HOUR_MS, "heat_water": 6.0 * HOUR_MS},
    "balanced_slack": {"charge_ev": 5.8 * HOUR_MS, "heat_water": 5.9 * HOUR_MS},
    "water_urgent": {"charge_ev": 6.0 * HOUR_MS, "heat_water": 0.75 * HOUR_MS},
}
POLICY_DELAYS = {
    "IndependentMultiAgent": (0,),
    "ConstraintCoordinator": (0, 300),
    "DeadlineAwareCoordinator": (0, 300),
    "CapacityAwareDeadlineCoordinator": (0, 300),
}


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
        for capacity in CAPACITIES_KW:
            base = make_episode("conflict" if capacity < 7.0 else "control")
            base["home"]["resources"]["max_power_kw"] = capacity
            next(rule for rule in base["conflict_rules"] if rule["type"] == "C3")["capacity"] = capacity
            base["home"]["resources"]["task_power_bounds_kw"] = {
                "charge_ev": 4.0, "heat_water": 3.0,
            }
            for profile, deadlines in DEADLINE_PROFILES_MS.items():
                episode = deepcopy(base)
                for task in episode["task_stream"]:
                    task["completion_deadline_ms"] = int(deadlines[task["task_id"]])
                for policy, delays in POLICY_DELAYS.items():
                    for delay in delays:
                        trace, result = run_event_simulation(
                            deepcopy(episode), RecordedLatencyScriptedActions(latencies),
                            policy, "", coordination_delay_ms=delay,
                            shared_safety_gate=True,
                        )
                        rows.append({
                            "source_repetition": source_row["repetition"],
                            "capacity_kw": capacity,
                            "capacity_regime": "over_capacity" if capacity < 7.0 else (
                                "exact_capacity" if capacity == 7.0 else "safe_parallel"
                            ),
                            "deadline_profile": profile,
                            "deadlines_ms": deadlines,
                            "policy": policy,
                            "synthetic_coordination_delay_ms": delay,
                            "proposal_latency_by_task_ms": latencies,
                            "proposal_return_order": [event["task_id"] for event in trace["events"]
                                                       if event["type"] == "proposal_returned"],
                            "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                            "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                            "task_deadline_met": result["task_deadline_met"],
                            "all_deadlines_met": result["all_deadlines_met"],
                            "all_tasks_served": all(result["task_service"].values()),
                            "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                            "conflict_count": sum(result["conflict_counts"].values()),
                        })
    payload = {
        "schema_version": "ev-water-deadline-boundary-0.1",
        "status": "synthetic_parameter_sweep_one_task_template_not_independent_scenarios",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "historical_model_calls_are_sequential_logical_arrivals": True,
        "power_bounds_kw": {"charge_ev": 4.0, "heat_water": 3.0},
        "capacity_kw": CAPACITIES_KW,
        "deadline_profiles_ms": DEADLINE_PROFILES_MS,
        "coordination_delays_are_synthetic_ms": [0, 300],
        "same_shared_safety_gate_for_all_policies": True,
        "new_api_calls": 0,
        "real_devices": 0,
        "rows": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = run_pilot()
    print(json.dumps({"cells": len(report["rows"]), "output": str(OUTPUT)},
                     ensure_ascii=False))
