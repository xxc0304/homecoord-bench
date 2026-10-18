"""D03: a returned-home report releases a separate HVAC service task.

This is a synthetic command and message timing probe, not a thermal model.
The occupancy agent's completed report is causal: without it the comfort task
is never released. All policies use the same safety gate and proposals.
"""

from __future__ import annotations

import json
from copy import deepcopy

from evaluate import ROOT
from runtime.dry_run import DryRunClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation

OUT = ROOT / "results" / "d03_return_message_synthetic_20260928.json"
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
    "CentralSingleAgent",
)


class TimedClient(DryRunClient):
    def __init__(self, report_ms: int):
        self.report_ms = report_ms

    def decide(self, request: dict, instructions: str = "") -> dict:
        result = super().decide(request, instructions)
        self.last_latency_ms = self.report_ms if request["task"]["task_id"] == "report_return" else 1
        return result


def make_episode(energy_release_ms: int) -> dict:
    agents, tasks, tools, groundings = [], [], [], []
    specifications = (
        # task, agent, device, operation, release, duration, power, start effects, completion effects
        ("report_return", "OccupancyAgent", "occupancy_channel", "report_home", 800, 100, 0.0,
         {}, {"messages.return_reported": True, "request.comfort_active": True}),
        ("cool_on_return", "ComfortAgent", "living_hvac", "cool", 0, 1200, 1.4,
         {"devices.living_hvac": "cooling", "request.cooling_started": True}, {}),
        ("peak_off", "EnergyAgent", "living_hvac", "off", energy_release_ms, 300, 0.0,
         {"devices.living_hvac": "forced_off"}, {"devices.living_hvac": "forced_off"}),
    )
    for task_id, agent_id, target, operation, release, duration, power, start, finish in specifications:
        tool_name = f"do_{task_id}"
        requires = ([{"path": "messages.return_reported", "op": "eq", "value": True}]
                    if task_id == "cool_on_return" else [])
        agents.append({"agent_id": agent_id, "role": task_id, "tools": [tool_name],
                       "observable_state": ["messages.return_reported", "devices.living_hvac"],
                       "writable_resources": list(start | finish) + [f"devices.{target}"],
                       "goal_visibility": "local", "constraint_visibility": "local"})
        task = {"task_id": task_id, "agent_id": agent_id, "release_at_ms": release,
                "goal": {"report_return": "Publish the return observation.",
                         "cool_on_return": "Issue cooling after the return report.",
                         "peak_off": "Issue the peak-window off command."}[task_id],
                "priority": 90 if task_id == "cool_on_return" else 50,
                "required_action": {"target": target, "operation": operation},
                "action_template": {"target": target, "operation": operation,
                                    "parameters": {}, "duration_ms": duration,
                                    "power_kw": power, "requires": requires}}
        if task_id == "cool_on_return":
            task["release_after_task_completion"] = "report_return"
            task["completion_deadline_ms"] = 3500
        tasks.append(task)
        tools.append({"agent_id": agent_id, "tool_name": tool_name, "target": target,
                      "operation": operation, "parameters": [], "preconditions": requires,
                      "writable_path": ("messages.return_reported" if task_id == "report_return"
                                        else f"devices.{target}"),
                      "description": task["goal"]})
        groundings.append({"agent_id": agent_id, "task_id": task_id,
                           "target": target, "operation": operation,
                           "grounded_operation": operation, "start_effects": start,
                           "completion_effects": finish, "duration_ms": duration,
                           "power_kw": power})
    episode = {
        "episode_id": f"HC-D03-ENERGY-{energy_release_ms}", "base_episode_id": "HC-D03",
        "episode_release_at_ms": 0, "task_family": "return_message_direct_conflict",
        "source_type": "synthetic_message_command_timing", "data_tier": "mechanism_only",
        "review_status": "author_mechanism_pilot_not_benchmark",
        "home": {"resources": {"max_power_kw": 5.0}},
        "initial_state": {"version": 1, "values": {"messages": {"return_reported": False},
                                                  "request": {"comfort_active": False, "cooling_started": False},
                                                  "devices": {"living_hvac": "off"}}},
        "agents": agents, "task_stream": tasks, "tool_catalog": tools,
        "action_grounding": groundings, "tool_contract_version": "strict-v1",
        "simulation": {"command_latency_ms": 100},
        "exogenous_events": [
            {"at_ms": 800, "event": "resident_actual_return", "patch": {"resident.actual_home": True}},
            {"at_ms": 3000, "event": "comfort_request_window_ends", "patch": {"request.comfort_active": False}},
        ],
        "goals": [{"path": "messages.return_reported", "op": "eq", "value": True}],
        "constraints": [{"when": [{"path": "request.comfort_active", "op": "eq", "value": True},
                                  {"path": "request.cooling_started", "op": "eq", "value": True}],
                         "must": [{"path": "devices.living_hvac", "op": "neq", "value": "forced_off"}]}],
        "conflict_rules": [{"type": "C1", "a": {"target": "living_hvac", "operation": "cool"},
                            "b": {"target": "living_hvac", "operation": "off"}}],
        "variant": {"energy_release_ms": energy_release_ms,
                    "changed_factor": "energy_task_release_at_ms"},
        "calibration": {"status": "synthetic_message_and_service_window",
                        "physical_parameters_verified": False,
                        "excluded_claims": ["measured_thermal_comfort", "real_message_latency"]},
    }
    errors = validate_event_episode(episode)
    if errors:
        raise ValueError(errors)
    return episode


def run() -> dict:
    rows = []
    for energy_release in (200, 1150, 3200):
        episode = make_episode(energy_release)
        for report_latency in (1, 600):
            for policy in POLICIES:
                trace, result = run_event_simulation(
                    deepcopy(episode), TimedClient(report_latency), policy, "",
                    shared_safety_gate=True,
                )
                rows.append({
                    "energy_release_ms": energy_release, "report_latency_ms": report_latency,
                    "policy": policy, "process_valid_success": result["process_valid_success"],
                    "task_service": result["task_service"],
                    "all_tasks_served": all(result["task_service"].values()),
                    "task_deadline_met": result["task_deadline_met"],
                    "unsafe_onsets": result["state_constraint_violation_episode_count"],
                    "action_start": [(e["task_id"], e["timestamp_ms"]) for e in trace["events"]
                                     if e["type"] == "action_started"],
                    "task_release": [(e["task_id"], e["timestamp_ms"]) for e in trace["events"]
                                     if e["type"] == "task_released"],
                    "rejection_reasons": [e["reason"] for e in trace["events"]
                                          if e["type"] == "action_rejected"],
                })
    payload = {"status": "synthetic_mechanism_only_not_benchmark", "api_calls": 0,
               "episodes": [make_episode(t) for t in (200, 1150, 3200)], "rows": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps({"rows": len(run()["rows"]), "output": str(OUT)}, ensure_ascii=False))
