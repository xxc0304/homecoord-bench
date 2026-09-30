"""C3 structural-generalization probe across 2, 3, and 5 agents.

This is a controlled mechanism experiment.  It exhaustively varies proposal
arrival order while holding task semantics fixed inside each template.  Device
powers, durations, and deadlines are declared benchmark factors rather than
claims about a representative household.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from evaluate import ROOT
from probe_c3_three_load import ScriptedProposalClient
from runtime.event_simulator import run_event_simulation


OUTPUT = ROOT / "results" / "c3_structural_generalization_20260929.json"
MINUTE = 60_000
PRESSURES = (0.8, 1.0, 1.2, 1.6)
POLICIES = (
    "IndependentMultiAgent",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
    "CapacityAwareDeadlineCoordinator",
)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    agent_id: str
    device: str
    operation: str
    power_kw: float
    duration_min: int
    deadline_min: int
    priority: int


TASK_POOL = (
    TaskSpec("cook_dinner", "CookingAgent", "cooktop", "cook", 2.0, 25, 30, 100),
    TaskSpec("dry_laundry", "LaundryAgent", "dryer", "dry", 2.5, 60, 120, 80),
    TaskSpec("wash_dishes", "DishwashingAgent", "dishwasher", "wash", 1.2, 90, 180, 60),
    TaskSpec("heat_water", "WaterHeatingAgent", "water_heater", "heat", 3.0, 45, 90, 90),
    TaskSpec("charge_ev", "EVChargingAgent", "ev_charger", "charge", 3.3, 180, 480, 40),
)


def task_specs(agent_count: int) -> tuple[TaskSpec, ...]:
    if agent_count == 2:
        return TASK_POOL[:2]
    if agent_count == 3:
        return TASK_POOL[:3]
    if agent_count == 5:
        return TASK_POOL
    raise ValueError(f"unsupported agent count: {agent_count}")


def make_episode_from_specs(template_id: str, specs: tuple[TaskSpec, ...],
                            pressure: float) -> dict[str, Any]:
    """Build one controlled C3 episode from an explicit task structure."""
    agent_count = len(specs)
    total_power = sum(task.power_kw for task in specs)
    capacity = round(total_power / pressure, 6)
    agents: list[dict[str, Any]] = []
    stream: list[dict[str, Any]] = []
    grounding: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    initial_devices: dict[str, str] = {}
    goals: list[dict[str, Any]] = []
    bounds: dict[str, float] = {}

    for task in specs:
        agents.append({
            "agent_id": task.agent_id,
            "role": task.task_id,
            "tools": [f"start_{task.device}"],
            "observable_state": [f"devices.{task.device}"],
            "writable_resources": [f"devices.{task.device}"],
            "goal_visibility": "local",
            "constraint_visibility": "local",
        })
        stream.append({
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "release_at_ms": 0,
            "goal": f"Complete {task.task_id} within {task.deadline_min} minutes.",
            "priority": task.priority,
            "completion_deadline_ms": task.deadline_min * MINUTE,
            "required_action": {"target": task.device, "operation": task.operation},
            "action_template": {
                "target": task.device,
                "operation": task.operation,
                "parameters": {},
                "duration_ms": task.duration_min * MINUTE,
                "power_kw": task.power_kw,
                "requires": [
                    {"path": f"devices.{task.device}", "op": "eq", "value": "idle"}
                ],
            },
        })
        grounding.append({
            "agent_id": task.agent_id,
            "task_id": task.task_id,
            "target": task.device,
            "operation": task.operation,
            "grounded_operation": task.operation,
            "start_effects": {f"devices.{task.device}": "running"},
            "completion_effects": {f"devices.{task.device}": "complete"},
            "effects": {f"devices.{task.device}": "complete"},
            "duration_ms": task.duration_min * MINUTE,
            "power_kw": task.power_kw,
        })
        catalog.append({
            "agent_id": task.agent_id,
            "tool_name": f"start_{task.device}",
            "target": task.device,
            "operation": task.operation,
            "parameters": [],
            "preconditions": [
                {"path": f"devices.{task.device}", "op": "eq", "value": "idle"}
            ],
            "description": (
                f"Start a fixed {task.duration_min}-minute cycle at nominal "
                f"{task.power_kw} kW."
            ),
        })
        initial_devices[task.device] = "idle"
        goals.append({"path": f"devices.{task.device}", "op": "eq", "value": "complete"})
        bounds[task.task_id] = task.power_kw

    return {
        "episode_id": f"HC-C3-{template_id}-RHO-{pressure:g}",
        "base_episode_id": f"HC-C3-{template_id}",
        "task_family": "resource_capacity_conflict",
        "source_type": "controlled_structural_generalization_probe",
        "review_status": "mechanism_probe_not_frozen_benchmark_data",
        "episode_release_at_ms": 0,
        "home": {"resources": {
            "max_power_kw": capacity,
            "task_power_bounds_kw": bounds,
        }},
        "initial_state": {"version": 1, "values": {"devices": initial_devices}},
        "agents": agents,
        "task_stream": stream,
        "exogenous_events": [],
        "goals": goals,
        "constraints": [],
        "conflict_rules": [{"type": "C3", "capacity": capacity}],
        "action_grounding": grounding,
        "tool_catalog": catalog,
        "tool_contract_version": "strict-v1",
        "simulation": {"command_latency_ms": 100},
        "resource_pressure": {
            "load_to_capacity_ratio": pressure,
            "sum_nominal_requested_power_kw": total_power,
            "capacity_kw": capacity,
            "source": "controlled_benchmark_factor",
        },
        "scenario_assumptions": {
            "power_semantics": "constant nominal load during a fixed noninterruptible cycle",
            "physical_calibration": "none",
            "purpose": "mechanism isolation and structural generalization only",
        },
    }


def make_episode(agent_count: int, pressure: float) -> dict[str, Any]:
    return make_episode_from_specs(
        f"SCALE-{agent_count}", task_specs(agent_count), pressure
    )


def arrival_orders(specs: tuple[TaskSpec, ...]) -> Iterable[tuple[str, ...]]:
    """Exhaustive for <=3 agents; deterministic broad coverage for 5 agents."""
    ids = tuple(task.task_id for task in specs)
    if len(ids) <= 3:
        return itertools.permutations(ids)
    # Exhaustive 5! remains cheap and avoids choosing a favorable subset.
    return itertools.permutations(ids)


def latencies_for_order(order: tuple[str, ...]) -> dict[str, int]:
    # Only order varies.  A 200 ms gap avoids timestamp ties.
    return {task_id: 800 + rank * 200 for rank, task_id in enumerate(order)}


def run(output: Path = OUTPUT) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for agent_count in (2, 3, 5):
        specs = task_specs(agent_count)
        for order in arrival_orders(specs):
            latencies = latencies_for_order(order)
            for pressure in PRESSURES:
                episode = make_episode(agent_count, pressure)
                for policy in POLICIES:
                    trace, result = run_event_simulation(
                        episode,
                        ScriptedProposalClient(latencies),
                        policy,
                        "controlled arrival-order probe",
                        shared_safety_gate=True,
                    )
                    rows.append({
                        "agent_count": agent_count,
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
    for agent_count in (2, 3, 5):
        count_key = str(agent_count)
        summary[count_key] = {}
        for pressure in PRESSURES:
            pressure_key = f"{pressure:g}"
            summary[count_key][pressure_key] = {}
            for policy in POLICIES:
                subset = [
                    row for row in rows
                    if row["agent_count"] == agent_count
                    and row["pressure"] == pressure
                    and row["policy"] == policy
                ]
                summary[count_key][pressure_key][policy] = {
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
        "schema_version": "c3-structural-generalization-0.1",
        "status": "controlled_synthetic_mechanism_probe_not_benchmark_data",
        "api_calls": 0,
        "agent_counts": [2, 3, 5],
        "pressures": list(PRESSURES),
        "arrival_order_design": "all permutations within each task template",
        "templates_are_nested": True,
        "independent_base_templates_claimed": False,
        "summary": summary,
        "rows": rows,
        "limitations": [
            "The 2-, 3-, and 5-agent templates are nested scale variants, not three independent homes.",
            "Powers, fixed cycles, deadlines, and arrival gaps are controlled synthetic factors.",
            "Scripted valid proposals isolate scheduling and do not measure language understanding.",
            "The shared safety gate prevents unsafe starts and may convert a conflict into lost service.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    payload = run()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"rows={len(payload['rows'])}; wrote={OUTPUT}")
