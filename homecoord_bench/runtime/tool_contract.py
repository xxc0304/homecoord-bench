"""Optional strict tool-call validation for review-only benchmark drafts."""

from __future__ import annotations

from typing import Any


def validate_tool_call(episode: dict[str, Any], agent_id: str,
                       task_id: str, action: dict[str, Any]) -> str | None:
    """Return a stable rejection reason, or None when an action is authorized.

    Legacy episodes keep their original semantics. Only episodes opting into
    strict-v1 are checked, avoiding silent changes to historical experiment data.
    """
    if episode.get("tool_contract_version") != "strict-v1":
        return None
    agent = next((a for a in episode["agents"] if a["agent_id"] == agent_id), None)
    if agent is None:
        return "unknown_agent"
    matches = [item for item in episode.get("tool_catalog", [])
               if item.get("agent_id") == agent_id
               and item.get("target") == action.get("target")
               and item.get("operation") == action.get("operation")]
    if len(matches) != 1:
        return "tool_not_authorized"
    tool = matches[0]
    if tool.get("tool_name") not in agent.get("tools", []):
        return "tool_not_authorized"
    if f"devices.{action['target']}" not in agent.get("writable_resources", []):
        return "target_not_writable"
    grounding = [item for item in episode.get("action_grounding", [])
                 if item.get("agent_id") == agent_id
                 and item.get("task_id") == task_id
                 and item.get("target") == action["target"]
                 and item.get("operation") == action["operation"]]
    if len(grounding) != 1:
        return "ungrounded_tool_action"
    entries = action.get("parameters", [])
    if not isinstance(entries, list) or any(not isinstance(p, dict) for p in entries):
        return "invalid_tool_parameters"
    values = {p.get("name"): p.get("value") for p in entries}
    if len(values) != len(entries):
        return "invalid_tool_parameters"
    specs = {p["name"]: p for p in tool.get("parameters", [])}
    if set(values) - set(specs) or any(p.get("required") and name not in values
                                     for name, p in specs.items()):
        return "invalid_tool_parameters"
    for name, value in values.items():
        spec = specs[name]
        declared_type = spec.get("type")
        if declared_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return "invalid_tool_parameters"
        elif declared_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return "invalid_tool_parameters"
        elif declared_type == "boolean":
            if not isinstance(value, bool):
                return "invalid_tool_parameters"
        elif declared_type == "string":
            if not isinstance(value, str):
                return "invalid_tool_parameters"
        else:
            return "invalid_tool_parameters"
        if "minimum" in spec and value < spec["minimum"]:
            return "invalid_tool_parameters"
        if "maximum" in spec and value > spec["maximum"]:
            return "invalid_tool_parameters"
    requirements = action.get("requires", [])
    for required in tool.get("preconditions", []):
        if not any(r.get("path") == required["path"]
                   and r.get("op") == required["op"]
                   and r.get("value") == required["value"] for r in requirements):
            return "missing_tool_precondition"
    return None
