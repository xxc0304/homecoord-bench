"""Distinct C3 pilot: three appliance cycles share a constrained power source.

The device values are explicit scenario assumptions, not measured appliance
traces. The first dry run tests event and scoring semantics before model calls.
"""

from __future__ import annotations

import json

from evaluate import ROOT
from runtime.dry_run import DryRunClient
from runtime.event_simulator import run_event_simulation


OUTPUT = ROOT / "results" / "c3_three_load_dry_pilot_20260928.json"
MINUTE = 60_000
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
)
TASKS = (
    # Task name, agent, device, operation, power kW, fixed cycle min,
    # completion deadline min, priority, release ms, user-facing goal.
    ("cook_dinner", "CookingAgent", "cooktop", "cook", 2.0, 25, 30, 100, 0,
     "Complete the induction cooking cycle for dinner within 30 minutes."),
    ("dry_laundry", "LaundryAgent", "dryer", "dry", 2.5, 60, 120, 80, 0,
     "Finish drying laundry before the household leaves in two hours."),
    ("wash_dishes", "DishwashingAgent", "dishwasher", "wash", 1.2, 90, 180, 60, 0,
     "Finish washing dishes within three hours."),
)


def make_episode(condition: str) -> dict:
    if condition not in {"conflict", "control"}:
        raise ValueError(condition)
    capacity = 3.5 if condition == "conflict" else 5.8
    agents = []
    stream = []
    groundings = []
    catalog = []
    goals = []
    initial_devices = {}
    task_bounds = {}
    for task_id, agent_id, device, operation, power, minutes, deadline, priority, release, goal in TASKS:
        agents.append({
            "agent_id": agent_id, "role": task_id,
            "tools": [f"start_{device}", f"stop_{device}"],
            "observable_state": [f"devices.{device}"],
            "writable_resources": [f"devices.{device}"],
            "goal_visibility": "local", "constraint_visibility": "local",
        })
        stream.append({
            "task_id": task_id, "agent_id": agent_id, "release_at_ms": release,
            "goal": goal, "priority": priority,
            "completion_deadline_ms": deadline * MINUTE,
            "required_action": {"target": device, "operation": operation},
            "action_template": {"target": device, "operation": operation,
                                "parameters": {}, "duration_ms": minutes * MINUTE,
                                "power_kw": power, "requires": [
                                    {"path": f"devices.{device}", "op": "eq", "value": "idle"}
                                ]},
        })
        groundings.append({
            "agent_id": agent_id, "task_id": task_id,
            "target": device, "operation": operation,
            "grounded_operation": operation,
            "start_effects": {f"devices.{device}": "running"},
            "completion_effects": {f"devices.{device}": "complete"},
            "effects": {f"devices.{device}": "complete"},
            "duration_ms": minutes * MINUTE, "power_kw": power,
        })
        catalog.extend((
            {"agent_id": agent_id, "tool_name": f"start_{device}",
             "target": device, "operation": operation, "parameters": [],
             "preconditions": [{"path": f"devices.{device}", "op": "eq", "value": "idle"}],
             "description": f"Start one fixed {minutes}-minute cycle at nominal {power} kW."},
            {"agent_id": agent_id, "tool_name": f"stop_{device}",
             "target": device, "operation": "off", "parameters": [],
             "description": "Leave this appliance off."},
        ))
        # An off proposal is authorized but cannot satisfy the required task.
        groundings.append({
            "agent_id": agent_id, "task_id": task_id,
            "target": device, "operation": "off", "grounded_operation": "off",
            "effects": {f"devices.{device}": "idle"},
            "duration_ms": 100, "power_kw": 0.0,
        })
        goals.append({"path": f"devices.{device}", "op": "eq", "value": "complete"})
        initial_devices[device] = "idle"
        task_bounds[task_id] = power
    return {
        "episode_id": f"HC-C3-THREE-LOAD-{condition.upper()}",
        "base_episode_id": "HC-C3-THREE-LOAD",
        "task_family": "resource_capacity_conflict",
        "source_type": "synthetic_fixed_appliance_cycle_pilot",
        "review_status": "author_design_review_only",
        "episode_release_at_ms": 0,
        "home": {"resources": {"max_power_kw": capacity,
                               "task_power_bounds_kw": task_bounds}},
        "initial_state": {"version": 1, "values": {"devices": initial_devices}},
        "agents": agents, "task_stream": stream,
        "exogenous_events": [], "goals": goals, "constraints": [],
        "conflict_rules": [{"type": "C3", "capacity": capacity}],
        "action_grounding": groundings, "tool_catalog": catalog,
        "tool_contract_version": "strict-v1",
        "simulation": {"command_latency_ms": 100},
        "scenario_assumptions": {
            "power_semantics": "constant nominal load throughout each fixed noninterruptible cycle",
            "power_source": "assumed shared 3.5 kW backup limit versus 5.8 kW grid limit",
            "deadline_source": "illustrative household requests, not observed timestamps",
            "calibration_status": "none",
            "same_tasks_proposals_and_device_cycles_across_conditions": True,
        },
    }


class ScriptedProposalClient(DryRunClient):
    def __init__(self, latencies_ms: dict[str, int]):
        self.latencies_ms = latencies_ms

    def decide(self, request: dict, instructions: str = "") -> dict:
        self.last_latency_ms = self.latencies_ms[request["task"]["task_id"]]
        return super().decide(request, instructions)


def run_dry_pilot() -> dict:
    # Responses arrive in reverse urgency order. This checks whether each
    # policy handles three-way resource contention rather than replaying C3's
    # prior two-task EV/water ordering.
    latencies = {"cook_dinner": 1800, "dry_laundry": 1200, "wash_dishes": 1000}
    rows = []
    for condition in ("conflict", "control"):
        episode = make_episode(condition)
        for policy in POLICIES:
            trace, result = run_event_simulation(
                episode, ScriptedProposalClient(latencies), policy, "",
                shared_safety_gate=True,
            )
            rows.append({
                "condition": condition, "policy": policy,
                "latencies_ms": latencies,
                "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                "task_service": result["task_service"],
                "task_deadline_met": result["task_deadline_met"],
                "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                "all_deadlines_met": result["all_deadlines_met"],
                "final_goal_success": result["final_goal_success"],
                "process_valid_success": result["process_valid_success"],
                "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                "rejection_reasons": [event["reason"] for event in trace["events"]
                                      if event["type"] == "action_rejected"],
                "start_order": [event["task_id"] for event in trace["events"]
                                if event["type"] == "action_started"],
            })
    payload = {
        "status": "synthetic_three_task_mechanism_check_scripted_proposals",
        "scenarios": {condition: make_episode(condition) for condition in ("conflict", "control")},
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run_dry_pilot()
    print(json.dumps({"rows": len(result["rows"]), "output": str(OUTPUT)}, ensure_ascii=False))
