"""Replication of the C3 wait/execute tradeoff on non-nested task templates.

The two templates use distinct device sets and deadline structures.  They are
controlled mechanism probes, not frozen benchmark episodes or observations of
real household frequencies.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from statistics import median
from typing import Any

from evaluate import ROOT
from probe_c3_structural_generalization import (
    POLICIES,
    PRESSURES,
    ScriptedProposalClient,
    TaskSpec,
    latencies_for_order,
    make_episode_from_specs,
)
from runtime.event_simulator import run_event_simulation


OUTPUT = ROOT / "results" / "c3_non_nested_template_replay_20260929.json"

TEMPLATES: dict[str, tuple[TaskSpec, ...]] = {
    # A short urgent task competes with longer meal and cleanup cycles on a
    # managed kitchen circuit.
    "KITCHEN_CIRCUIT": (
        TaskSpec("boil_water", "BeverageAgent", "kettle", "boil", 1.8, 5, 10, 100),
        TaskSpec("bake_meal", "CookingAgent", "oven", "bake", 3.0, 45, 60, 80),
        TaskSpec("wash_dishes", "DishwashingAgent", "dishwasher", "wash", 2.4, 90, 180, 50),
    ),
    # Morning services have two tight human-facing deadlines and two longer
    # deferrable cycles.  This differs from simply adding agents to the earlier
    # cook/dry/wash pool.
    "MORNING_DEPARTURE": (
        TaskSpec("dry_hair", "GroomingAgent", "hair_dryer", "dry", 1.6, 10, 15, 100),
        TaskSpec("heat_shower", "WaterHeatingAgent", "water_heater", "heat", 3.0, 60, 75, 95),
        TaskSpec("wash_clothes", "LaundryAgent", "washer", "wash", 2.0, 60, 150, 50),
        TaskSpec("charge_ev", "EVChargingAgent", "ev_charger", "charge", 3.3, 120, 210, 70),
    ),
}


def run(output: Path = OUTPUT) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for template_id, specs in TEMPLATES.items():
        task_ids = tuple(task.task_id for task in specs)
        for order in itertools.permutations(task_ids):
            latencies = latencies_for_order(order)
            for pressure in PRESSURES:
                episode = make_episode_from_specs(template_id, specs, pressure)
                for policy in POLICIES:
                    trace, result = run_event_simulation(
                        episode,
                        ScriptedProposalClient(latencies),
                        policy,
                        "controlled non-nested C3 replication",
                        shared_safety_gate=True,
                    )
                    rows.append({
                        "template_id": template_id,
                        "agent_count": len(specs),
                        "pressure": pressure,
                        "arrival_order": list(order),
                        "policy": policy,
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "all_tasks_served": all(result["task_service"].values()),
                        "all_deadlines_met": result["all_deadlines_met"],
                        "task_deadline_met": result["task_deadline_met"],
                        "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                        "process_valid_success": result["process_valid_success"],
                        "shared_safety_gate_rejection_count": result[
                            "shared_safety_gate_rejection_count"
                        ],
                        "start_order": [
                            event["task_id"] for event in trace["events"]
                            if event["type"] == "action_started"
                        ],
                    })

    summary: dict[str, Any] = {}
    for template_id, specs in TEMPLATES.items():
        summary[template_id] = {}
        for pressure in PRESSURES:
            pressure_key = f"{pressure:g}"
            summary[template_id][pressure_key] = {}
            for policy in POLICIES:
                subset = [
                    row for row in rows
                    if row["template_id"] == template_id
                    and row["pressure"] == pressure
                    and row["policy"] == policy
                ]
                summary[template_id][pressure_key][policy] = {
                    "orders": len(subset),
                    "all_tasks_served": sum(row["all_tasks_served"] for row in subset),
                    "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                    "process_valid_success": sum(row["process_valid_success"] for row in subset),
                    "median_first_action_start_latency_ms": median(
                        row["first_action_start_latency_ms"] for row in subset
                        if row["first_action_start_latency_ms"] is not None
                    ),
                }

    report = {
        "schema_version": "c3-non-nested-template-replication-0.1",
        "status": "controlled_synthetic_mechanism_probe_not_benchmark_data",
        "api_calls": 0,
        "templates": {
            template_id: {
                "agent_count": len(specs),
                "task_ids": [task.task_id for task in specs],
                "arrival_orders": len(tuple(itertools.permutations(specs))),
            }
            for template_id, specs in TEMPLATES.items()
        },
        "pressures": list(PRESSURES),
        "summary": summary,
        "rows": rows,
        "limitations": [
            "Both templates are researcher-designed controlled scheduling structures.",
            "Powers, cycles, deadlines, and proposal latency gaps require provenance review.",
            "Scripted valid proposals isolate coordination and do not test LLM understanding.",
            "These templates are independent of the prior nested task pool but are not independent homes.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    payload = run()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"rows={len(payload['rows'])}; wrote={OUTPUT}")
