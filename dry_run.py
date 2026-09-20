"""Deterministic client used to validate the agent I/O pipeline without an API."""

from __future__ import annotations

from typing import Any

from .protocol import assert_agent_decision


class DryRunClient:
    def decide(self, agent_request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        task = agent_request["task"]
        agent = agent_request["agent"]
        state_version = agent_request["state_version"]
        acting_role = task.get("agent_id") if agent["agent_id"] == "CentralAgent" else agent["agent_id"]
        episode_id = agent_request.get("base_episode_id", agent_request["episode_id"])
        template = task.get("action_template")
        if template is not None:
            decision = _decision_from_template(agent_request, template, state_version)
            assert_agent_decision(decision)
            return decision
        if acting_role == "EnergyAgent" and task["task_id"] == "energy":
            comfort_visible = agent_request.get("state", {}).get("request", {}).get("comfort_active") is True
            if comfort_visible:
                decision = {
                    "response_type": "action_proposal",
                    "actions": [{
                        "proposal_id": f"{agent_request['request_id']}:0",
                        "target": "living_hvac",
                        "operation": "cool",
                        "parameters": [{"name": "temperature_c", "value": 24}],
                        "based_on_state_version": state_version,
                        "requires": [{"path": "request.comfort_active", "op": "eq", "value": True, "range_min": None, "range_max": None}],
                        "estimated_duration_ms": 10000,
                        "estimated_power_kw": 1.2,
                    }],
                    "accepted_proposal_ids": [], "rejected_proposal_ids": [],
                    "defer_until_ms": None, "reason_code": "goal_progress",
                }
                assert_agent_decision(decision)
                return decision
        operation, target, parameters, requirements, duration, power = _action_for(
            episode_id, acting_role, task["task_id"]
        )
        decision = {
            "response_type": "action_proposal",
            "actions": [{
                "proposal_id": f"{agent_request['request_id']}:0",
                "target": target,
                "operation": operation,
                "parameters": [
                    {"name": name, "value": value}
                    for name, value in parameters.items()
                ],
                "based_on_state_version": state_version,
                "requires": [
                    {
                        "path": item["path"],
                        "op": item["op"],
                        "value": None if item["op"] == "between" else item["value"],
                        "range_min": item["value"][0] if item["op"] == "between" else None,
                        "range_max": item["value"][1] if item["op"] == "between" else None,
                    }
                    for item in requirements
                ],
                "estimated_duration_ms": duration,
                "estimated_power_kw": power,
            }],
            "accepted_proposal_ids": [],
            "rejected_proposal_ids": [],
            "defer_until_ms": None,
            "reason_code": "goal_progress",
        }
        assert_agent_decision(decision)
        return decision


def _action_for(episode_id: str, agent_id: str, task_id: str):
    actions = {
        ("HC-SEED-001", "LightingAgent", "light"): ("set_reading", "study_light", {"lux": 500}, [], 1000, 0.02),
        ("HC-SEED-001", "ClimateAgent", "climate"): ("cool", "bedroom_hvac", {"temperature_c": 25}, [], 3000, 1.2),
        ("HC-SEED-002", "ComfortAgent", "comfort"): ("cool", "living_hvac", {"temperature_c": 24}, [], 10000, 1.4),
        ("HC-SEED-002", "EnergyAgent", "energy"): ("off", "living_hvac", {}, [], 1000, 0.0),
        ("HC-SEED-003", "AirQualityAgent", "air"): ("open", "window", {}, [], 2000, 0.0),
        ("HC-SEED-003", "ClimateAgent", "heat"): ("heat_high", "heater", {}, [], 3000, 2.0),
        ("HC-SEED-004", "CleaningAgent", "clean"): ("clean", "robot", {}, [{"path": "living_room.occupied", "op": "eq", "value": False}], 3000, 0.2),
        ("HC-SEED-004", "CareAgent", "care"): ("update_occupancy", "living_room", {}, [], 100, 0.0),
    }
    return actions[(episode_id, agent_id, task_id)]


def _decision_from_template(
    agent_request: dict[str, Any], template: dict[str, Any], state_version: int
) -> dict[str, Any]:
    """Build a deterministic proposal from a task-local action template.

    Candidate episodes use this small adapter so adding a task does not require
    changing the seed-task dispatch table.  The template is still validated by
    the same provider-neutral decision protocol as model output.
    """
    requirements = []
    for item in template.get("requires", []):
        if item["op"] == "between":
            requirements.append({
                "path": item["path"], "op": item["op"], "value": None,
                "range_min": item["value"][0], "range_max": item["value"][1],
            })
        else:
            requirements.append({
                "path": item["path"], "op": item["op"], "value": item["value"],
                "range_min": None, "range_max": None,
            })
    action = {
        "proposal_id": f"{agent_request['request_id']}:0",
        "target": template["target"],
        "operation": template["operation"],
        "parameters": [
            {"name": name, "value": value}
            for name, value in template.get("parameters", {}).items()
        ],
        "based_on_state_version": state_version,
        "requires": requirements,
        "estimated_duration_ms": template.get("duration_ms"),
        "estimated_power_kw": template.get("power_kw"),
    }
    return {
        "response_type": "action_proposal",
        "actions": [action],
        "accepted_proposal_ids": [],
        "rejected_proposal_ids": [],
        "defer_until_ms": None,
        "reason_code": "goal_progress",
    }
