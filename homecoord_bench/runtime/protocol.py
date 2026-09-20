"""Provider-neutral request and decision protocol for benchmark agents."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any
from uuid import uuid4


NATIVE_SCALAR_SCHEMA = {
    "type": ["string", "number", "boolean", "null"],
    "description": "A native JSON scalar; do not encode JSON inside a string",
}


PARAMETER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "value": NATIVE_SCALAR_SCHEMA,
    },
    "required": ["name", "value"],
    "additionalProperties": False,
}

REQUIREMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "op": {"type": "string", "enum": ["eq", "neq", "lt", "lte", "gt", "gte", "between"]},
        "value": NATIVE_SCALAR_SCHEMA,
        "range_min": {"type": ["number", "null"]},
        "range_max": {"type": ["number", "null"]},
    },
    "required": ["path", "op", "value", "range_min", "range_max"],
    "additionalProperties": False,
}

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "proposal_id": {"type": "string"},
        "target": {"type": "string"},
        "operation": {"type": "string"},
        "parameters": {"type": "array", "items": PARAMETER_SCHEMA},
        "based_on_state_version": {"type": "integer"},
        "requires": {"type": "array", "items": REQUIREMENT_SCHEMA},
        "estimated_duration_ms": {"type": ["integer", "null"], "minimum": 0},
        "estimated_power_kw": {"type": ["number", "null"], "minimum": 0},
    },
    "required": [
        "proposal_id", "target", "operation", "parameters",
        "based_on_state_version", "requires", "estimated_duration_ms",
        "estimated_power_kw",
    ],
    "additionalProperties": False,
}

AGENT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "response_type": {
            "type": "string",
            "enum": ["action_proposal", "coordination_decision", "defer", "noop"],
        },
        "actions": {"type": "array", "maxItems": 1, "items": ACTION_SCHEMA},
        "accepted_proposal_ids": {"type": "array", "items": {"type": "string"}},
        "rejected_proposal_ids": {"type": "array", "items": {"type": "string"}},
        "defer_until_ms": {"type": ["integer", "null"], "minimum": 0},
        "reason_code": {
            "type": "string",
            "enum": [
                "goal_progress", "priority_resolution", "resource_conflict",
                "stale_state", "unsafe_precondition", "awaiting_state",
                "no_applicable_action",
            ],
        },
    },
    "required": [
        "response_type", "actions", "accepted_proposal_ids",
        "rejected_proposal_ids", "defer_until_ms", "reason_code",
    ],
    "additionalProperties": False,
}


def build_agent_request(
    episode: dict[str, Any],
    agent: dict[str, Any],
    task: dict[str, Any],
    *,
    architecture: str,
    current_time_ms: int,
    current_state: dict[str, Any] | None = None,
    state_version: int | None = None,
    pending_proposals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the exact provider-neutral input supplied to an agent."""
    source_state = deepcopy(episode["initial_state"]["values"] if current_state is None else current_state)
    observable = agent.get("observable_state", [])
    if observable == ["*"]:
        visible_state = source_state
    else:
        visible_state: dict[str, Any] = {}
        for path in dict.fromkeys([*observable, *agent.get("writable_resources", [])]):
            value = _get_path(source_state, path)
            if value is not _MISSING:
                _set_path(visible_state, path, deepcopy(value))
    return {
        "request_id": str(uuid4()),
        "episode_id": episode["episode_id"],
        "base_episode_id": episode.get("base_episode_id", episode["episode_id"]),
        "architecture": architecture,
        "current_time_ms": current_time_ms,
        "state_version": episode["initial_state"]["version"] if state_version is None else state_version,
        "state": visible_state,
        "agent": deepcopy(agent),
        "task": deepcopy(task),
        "goals": deepcopy(episode["goals"]),
        "constraints": deepcopy(
            episode["constraints"]
            if agent.get("constraint_visibility", "all") == "all"
            else agent.get("policy_constraints", [])
        ),
        "allowed_tools": deepcopy(agent.get("tools", [])),
        "pending_proposals": deepcopy(pending_proposals or []),
    }


_MISSING = object()


def _get_path(state: dict[str, Any], path: str) -> Any:
    current: Any = state
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_path(state: dict[str, Any], path: str, value: Any) -> None:
    current = state
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _validate_keys(value: dict[str, Any], required: set[str], context: str) -> list[str]:
    errors = [f"{context}: missing {key}" for key in sorted(required - value.keys())]
    errors.extend(f"{context}: unexpected {key}" for key in sorted(value.keys() - required))
    return errors


def _is_native_json_scalar(value: Any) -> bool:
    """Return whether a value fits the provider-compatible native JSON scalar subset."""
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def validate_agent_decision(decision: dict[str, Any]) -> list[str]:
    required = set(AGENT_DECISION_SCHEMA["required"])
    errors = _validate_keys(decision, required, "decision")
    if errors:
        return errors
    allowed_types = set(AGENT_DECISION_SCHEMA["properties"]["response_type"]["enum"])
    allowed_reasons = set(AGENT_DECISION_SCHEMA["properties"]["reason_code"]["enum"])
    if decision["response_type"] not in allowed_types:
        errors.append("decision: invalid response_type")
    if decision["reason_code"] not in allowed_reasons:
        errors.append("decision: invalid reason_code")
    if not isinstance(decision["actions"], list):
        errors.append("decision: actions must be a list")
        return errors
    action_required = set(ACTION_SCHEMA["required"])
    parameter_required = set(PARAMETER_SCHEMA["required"])
    requirement_required = set(REQUIREMENT_SCHEMA["required"])
    allowed_ops = set(REQUIREMENT_SCHEMA["properties"]["op"]["enum"])
    for index, action in enumerate(decision["actions"]):
        if not isinstance(action, dict):
            errors.append(f"action[{index}]: must be an object")
            continue
        errors.extend(_validate_keys(action, action_required, f"action[{index}]"))
        if isinstance(action.get("based_on_state_version"), bool) or not isinstance(action.get("based_on_state_version"), int):
            errors.append(f"action[{index}]: based_on_state_version must be an integer")
        parameters = action.get("parameters")
        if not isinstance(parameters, list):
            errors.append(f"action[{index}]: parameters must be a list")
        else:
            for parameter_index, parameter in enumerate(parameters):
                context = f"action[{index}].parameters[{parameter_index}]"
                if not isinstance(parameter, dict):
                    errors.append(f"{context}: must be an object")
                    continue
                errors.extend(_validate_keys(parameter, parameter_required, context))
                if not isinstance(parameter.get("name"), str):
                    errors.append(f"{context}: name must be a string")
                if "value" in parameter and not _is_native_json_scalar(parameter["value"]):
                    errors.append(f"{context}: value must be a native JSON scalar")
        requirements = action.get("requires")
        if not isinstance(requirements, list):
            errors.append(f"action[{index}]: requires must be a list")
        else:
            for requirement_index, requirement in enumerate(requirements):
                context = f"action[{index}].requires[{requirement_index}]"
                if not isinstance(requirement, dict):
                    errors.append(f"{context}: must be an object")
                    continue
                errors.extend(_validate_keys(requirement, requirement_required, context))
                if requirement.get("op") not in allowed_ops:
                    errors.append(f"{context}: invalid op")
                if not isinstance(requirement.get("path"), str):
                    errors.append(f"{context}: path must be a string")
                if "value" in requirement and not _is_native_json_scalar(requirement["value"]):
                    errors.append(f"{context}: value must be a native JSON scalar")
                for bound in ("range_min", "range_max"):
                    bound_value = requirement.get(bound)
                    if bound_value is not None and (
                        isinstance(bound_value, bool)
                        or not isinstance(bound_value, (int, float))
                        or (isinstance(bound_value, float) and not math.isfinite(bound_value))
                    ):
                        errors.append(f"{context}: {bound} must be a number or null")
                if requirement.get("op") == "between":
                    if requirement.get("value") is not None:
                        errors.append(f"{context}: between requires value to be null")
                    if requirement.get("range_min") is None or requirement.get("range_max") is None:
                        errors.append(f"{context}: between requires range_min and range_max")
                elif requirement.get("range_min") is not None or requirement.get("range_max") is not None:
                    errors.append(f"{context}: non-between requirements cannot use range bounds")
        for field in ("estimated_duration_ms", "estimated_power_kw"):
            value = action.get(field)
            if isinstance(value, bool) or (value is not None and not isinstance(value, (int, float))):
                errors.append(f"action[{index}]: {field} must be numeric or null")
            elif value is not None and value < 0:
                errors.append(f"action[{index}]: {field} must be non-negative")
    if decision["response_type"] == "action_proposal" and not decision["actions"]:
        errors.append("decision: action_proposal requires at least one action")
    if len(decision["actions"]) > 1:
        errors.append("decision: at most one action is allowed per task decision")
    if decision["response_type"] in {"defer", "noop"} and decision["actions"]:
        errors.append("decision: defer/noop cannot contain actions")
    for field in ("accepted_proposal_ids", "rejected_proposal_ids"):
        if not isinstance(decision[field], list) or not all(isinstance(item, str) for item in decision[field]):
            errors.append(f"decision: {field} must be a list of strings")
    defer_until = decision["defer_until_ms"]
    if isinstance(defer_until, bool) or (defer_until is not None and not isinstance(defer_until, int)):
        errors.append("decision: defer_until_ms must be an integer or null")
    return errors


def assert_agent_decision(decision: dict[str, Any]) -> None:
    errors = validate_agent_decision(decision)
    if errors:
        raise ValueError("; ".join(errors))
