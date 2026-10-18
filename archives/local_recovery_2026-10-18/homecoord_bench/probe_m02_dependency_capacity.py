"""M02 mechanism pilot: dryer task is released by actual washer completion.

Three agents share a power budget. Fixed nominal loads and deadlines are
explicit synthetic stress conditions, not measured household evidence.
"""

from __future__ import annotations

import json
from copy import deepcopy

from evaluate import ROOT
from runtime.dry_run import DryRunClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation

OUT = ROOT / "results" / "m02_dependency_capacity_20260928.json"
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
    "CentralSingleAgent",
)
TASKS = (
    # id, agent, device, operation, kW, duration ms, deadline ms, predecessor
    ("wash_laundry", "LaundryAgent", "washer", "wash", 1.0, 1200, 1600, None),
    ("dry_laundry", "DryingAgent", "dryer", "dry", 2.2, 1200, 4400, "wash_laundry"),
    ("heat_water", "WaterAgent", "heater", "heat", 1.5, 1500, 3100, None),
)
CAPACITY = {"tight": 2.5, "loose": 4.0}
LATENCIES = {
    "early_water": {"wash_laundry": 1, "dry_laundry": 1, "heat_water": 1},
    "late_water": {"wash_laundry": 1, "dry_laundry": 1, "heat_water": 1400},
}


class RecordedLatencyDryRun(DryRunClient):
    def __init__(self, latencies: dict[str, int]):
        self.latencies = latencies

    def decide(self, request: dict, instructions: str = "") -> dict:
        decision = super().decide(request, instructions)
        self.last_latency_ms = self.latencies[request["task"]["task_id"]]
        return decision


def make_episode(capacity_condition: str) -> dict:
    if capacity_condition not in CAPACITY:
        raise ValueError(capacity_condition)
    capacity = CAPACITY[capacity_condition]
    agents, stream, catalog, grounding, goals = [], [], [], [], []
    state, bounds = {}, {}
    for task_id, agent_id, device, operation, power, duration, deadline, predecessor in TASKS:
        start_tool = f"start_{device}"
        stop_tool = f"stop_{device}"
        agents.append({
            "agent_id": agent_id, "role": task_id,
            "tools": [start_tool, stop_tool],
            "observable_state": [f"devices.{device}"],
            "writable_resources": [f"devices.{device}"],
            "goal_visibility": "local", "constraint_visibility": "local",
        })
        task = {
            "task_id": task_id, "agent_id": agent_id, "release_at_ms": 0,
            "completion_deadline_ms": deadline,
            "goal": f"Complete the {operation} cycle before the stated deadline.",
            "priority": 100 if task_id == "wash_laundry" else 80,
            "required_action": {"target": device, "operation": operation},
            "action_template": {
                "target": device, "operation": operation,
                "parameters": {}, "duration_ms": duration, "power_kw": power,
                "requires": [{"path": f"devices.{device}", "op": "eq", "value": "idle"}],
            },
        }
        if predecessor:
            task["release_after_task_completion"] = predecessor
            task["release_delay_ms"] = 0
        stream.append(task)
        catalog.extend((
            {
                "agent_id": agent_id, "tool_name": start_tool,
                "target": device, "operation": operation, "parameters": [],
                "preconditions": deepcopy(task["action_template"]["requires"]),
                "description": f"Start a synthetic noninterruptible {operation} cycle.",
            },
            {
                "agent_id": agent_id, "tool_name": stop_tool,
                "target": device, "operation": "off", "parameters": [],
                "description": "Leave the appliance idle.",
            },
        ))
        grounding.extend((
            {
                "agent_id": agent_id, "task_id": task_id,
                "target": device, "operation": operation,
                "grounded_operation": operation,
                "start_effects": {f"devices.{device}": "running"},
                "completion_effects": {f"devices.{device}": "complete"},
                "duration_ms": duration, "power_kw": power,
            },
            {
                "agent_id": agent_id, "task_id": task_id,
                "target": device, "operation": "off",
                "grounded_operation": "off",
                "effects": {f"devices.{device}": "idle"},
                "duration_ms": 100, "power_kw": 0.0,
            },
        ))
        goals.append({"path": f"devices.{device}", "op": "eq", "value": "complete"})
        state[device] = "idle"
        bounds[task_id] = power
    episode = {
        "episode_id": f"HC-M02-{capacity_condition.upper()}",
        "base_episode_id": "HC-M02",
        "task_family": "resource_capacity_with_completion_trigger",
        "source_type": "synthetic_fixed_cycle_mechanism_pilot",
        "review_status": "author_mechanism_pilot_not_benchmark",
        "data_tier": "mechanism_only",
        "episode_release_at_ms": 0,
        "home": {"resources": {
            "max_power_kw": capacity,
            "capacity_scope": "synthetic_managed_load_budget",
            "task_power_bounds_kw": bounds,
        }},
        "initial_state": {"version": 1, "values": {"devices": state}},
        "agents": agents, "task_stream": stream, "exogenous_events": [],
        "goals": goals, "constraints": [],
        "conflict_rules": [{"type": "C3", "capacity": capacity}],
        "tool_contract_version": "strict-v1",
        "tool_catalog": catalog, "action_grounding": grounding,
        "simulation": {"command_latency_ms": 100},
        "calibration": {"status": "synthetic_fixed_cycle", "physical_parameters_verified": False},
        "variant": {"capacity_condition": capacity_condition, "changed_factor": "managed_load_budget_kw"},
    }
    issues = validate_event_episode(episode)
    if issues:
        raise ValueError(issues)
    return episode


def run() -> dict:
    rows = []
    for capacity_condition in CAPACITY:
        episode = make_episode(capacity_condition)
        for latency_condition, latencies in LATENCIES.items():
            for policy in POLICIES:
                trace, result = run_event_simulation(
                    deepcopy(episode), RecordedLatencyDryRun(latencies), policy, "",
                    shared_safety_gate=True,
                )
                releases = [
                    {k: event.get(k) for k in ("task_id", "timestamp_ms", "trigger_task_id")}
                    for event in trace["events"] if event["type"] == "task_released"
                ]
                completions = [
                    {k: event.get(k) for k in ("task_id", "timestamp_ms")}
                    for event in trace["events"] if event["type"] == "action_completed"
                ]
                rows.append({
                    "capacity_condition": capacity_condition,
                    "latency_condition": latency_condition,
                    "policy": policy,
                    "task_releases": releases,
                    "action_completions": completions,
                    "task_service": result["task_service"],
                    "task_deadline_met": result["task_deadline_met"],
                    "all_deadlines_met": result["all_deadlines_met"],
                    "process_valid_success": result["process_valid_success"],
                    "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                })
    report = {
        "status": "synthetic_dependency_and_capacity_mechanism_pilot",
        "api_calls": 0,
        "capacity_kw": CAPACITY,
        "scripted_proposal_latency_ms": LATENCIES,
        "episodes": {condition: make_episode(condition) for condition in CAPACITY},
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps({"rows": len(report["rows"]), "output": str(OUT)}, ensure_ascii=False))
