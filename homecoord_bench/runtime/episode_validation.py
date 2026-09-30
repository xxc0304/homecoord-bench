"""Runtime checks for event-simulation episodes.

The repository JSON schema describes the interchange format, while these checks
protect the event queue from malformed clocks, broken references, and invalid
physical quantities that would otherwise fail midway through a batch.
"""

from __future__ import annotations

import math
from typing import Any


_CONDITION_OPS = {"eq", "neq", "lt", "lte", "gt", "gte", "between"}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _check_condition(value: Any, context: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return
    if not isinstance(value.get("path"), str) or not value["path"].strip():
        errors.append(f"{context}.path must be a non-empty string")
    operator = value.get("op")
    if not isinstance(operator, str) or operator not in _CONDITION_OPS:
        errors.append(f"{context}.op must be one of {sorted(_CONDITION_OPS)}")
    if "value" not in value:
        errors.append(f"{context}.value is required")
    if operator == "between":
        bounds = value.get("value")
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            errors.append(f"{context}.value must contain two bounds for between")


def validate_event_episode(episode: dict[str, Any]) -> list[str]:
    """Return actionable validation errors before scheduling any episode events."""
    if not isinstance(episode, dict):
        return ["episode must be an object"]

    errors: list[str] = []
    episode_id = episode.get("episode_id")
    if not isinstance(episode_id, str) or not episode_id:
        errors.append("episode_id must be a non-empty string")

    episode_release = episode.get("episode_release_at_ms")
    if not _is_int(episode_release) or episode_release < 0:
        errors.append("episode_release_at_ms must be a non-negative integer")
        episode_release = 0

    initial = episode.get("initial_state")
    if not isinstance(initial, dict):
        errors.append("initial_state must be an object")
        initial = {}
    version = initial.get("version")
    if not _is_int(version) or version < 0:
        errors.append("initial_state.version must be a non-negative integer")
    if not isinstance(initial.get("values"), dict):
        errors.append("initial_state.values must be an object")

    agents = episode.get("agents")
    if not isinstance(agents, list) or not agents:
        errors.append("agents must be a non-empty list")
        agents = []
    elif len(agents) < 2:
        errors.append("event episode must contain at least two agents")
    agent_ids: list[str] = []
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict) or not isinstance(agent.get("agent_id"), str) or not agent["agent_id"]:
            errors.append(f"agents[{index}].agent_id must be a non-empty string")
            continue
        agent_ids.append(agent["agent_id"])
    if len(agent_ids) != len(set(agent_ids)):
        errors.append("agents contains duplicate agent_id values")
    known_agents = set(agent_ids)

    tasks = episode.get("task_stream")
    if not isinstance(tasks, list):
        errors.append("task_stream must be a list")
        tasks = []
    elif len(tasks) < 2:
        errors.append("event episode must contain at least two asynchronous tasks")
    task_ids: list[str] = []
    known_tasks: set[str] = set()
    tasks_by_id: dict[str, dict[str, Any]] = {}
    for index, task in enumerate(tasks):
        context = f"task_stream[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{context} must be an object")
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            errors.append(f"{context}.task_id must be a non-empty string")
        else:
            task_ids.append(task_id)
            known_tasks.add(task_id)
            tasks_by_id[task_id] = task
        agent_id = task.get("agent_id")
        if not isinstance(agent_id, str) or agent_id not in known_agents:
            errors.append(f"{context}.agent_id must reference an episode agent")
        released = task.get("release_at_ms")
        if not _is_int(released) or released < episode_release:
            errors.append(f"{context}.release_at_ms must be an integer at or after episode_release_at_ms")
        deadline = task.get("completion_deadline_ms")
        if deadline is not None and (not _is_int(deadline) or deadline < 0):
            errors.append(f"{context}.completion_deadline_ms must be a non-negative integer or null")
        if "acceptable_actions" in task:
            specs = task["acceptable_actions"]
            if task.get("required_action"):
                errors.append(f"{context} cannot mix required_action and acceptable_actions")
            if not isinstance(specs, list) or not specs or any(
                not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s[k] for k in ("target", "operation"))
                for s in specs
            ):
                errors.append(f"{context}.acceptable_actions must explicitly name target and operation")
    if len(task_ids) != len(set(task_ids)):
        errors.append("task_stream contains duplicate task_id values")

    exogenous = episode.get("exogenous_events", [])
    if not isinstance(exogenous, list):
        errors.append("exogenous_events must be a list")
        exogenous = []
    for index, event in enumerate(exogenous):
        context = f"exogenous_events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{context} must be an object")
            continue
        at_ms = event.get("at_ms")
        if not _is_int(at_ms) or at_ms < episode_release:
            errors.append(f"{context}.at_ms must be an integer at or after episode_release_at_ms")
        if not isinstance(event.get("patch", {}), dict):
            errors.append(f"{context}.patch must be an object")
        new_version = event.get("new_state_version")
        if new_version is not None and (not _is_int(new_version) or new_version < 0):
            errors.append(f"{context}.new_state_version must be a non-negative integer")

    simulation = episode.get("simulation", {})
    if not isinstance(simulation, dict):
        errors.append("simulation must be an object")
    else:
        command_latency = simulation.get("command_latency_ms", 0)
        if not _is_int(command_latency) or command_latency < 0:
            errors.append("simulation.command_latency_ms must be a non-negative integer")

    home = episode.get("home", {})
    resources = home.get("resources", {}) if isinstance(home, dict) else None
    if not isinstance(resources, dict):
        errors.append("home.resources must be an object when present")
    else:
        if "max_power_kw" in resources and not _is_finite_nonnegative_number(resources["max_power_kw"]):
            errors.append("home.resources.max_power_kw must be a finite non-negative number")
        bounds = resources.get("task_power_bounds_kw")
        if bounds is not None:
            if not isinstance(bounds, dict):
                errors.append("home.resources.task_power_bounds_kw must be an object")
            else:
                task_ids = {task.get("task_id") for task in episode.get("task_stream", [])
                            if isinstance(task, dict)}
                for task_id, power_kw in bounds.items():
                    if task_id not in task_ids or not _is_finite_nonnegative_number(power_kw):
                        errors.append(
                            f"home.resources.task_power_bounds_kw.{task_id} must name a task "
                            "and contain a finite non-negative number"
                        )

    for name in ("goals", "constraints"):
        records = episode.get(name)
        if not isinstance(records, list):
            errors.append(f"{name} must be a list")
            continue
        if name == "goals" and not records:
            errors.append("goals must contain at least one goal")
        for index, record in enumerate(records):
            context = f"{name}[{index}]"
            if name == "goals":
                _check_condition(record, context, errors)
                continue
            if not isinstance(record, dict):
                errors.append(f"{context} must be an object")
                continue
            for side in ("when", "must"):
                conditions = record.get(side, [])
                if not isinstance(conditions, list):
                    errors.append(f"{context}.{side} must be a list")
                    continue
                for condition_index, condition in enumerate(conditions):
                    _check_condition(condition, f"{context}.{side}[{condition_index}]", errors)

    rules = episode.get("conflict_rules", [])
    if not isinstance(rules, list):
        errors.append("conflict_rules must be a list")
        rules = []
    c3_count = 0
    for index, rule in enumerate(rules):
        context = f"conflict_rules[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{context} must be an object")
            continue
        rule_type = rule.get("type")
        if rule_type == "C3":
            c3_count += 1
            if not _is_finite_nonnegative_number(rule.get("capacity")):
                errors.append(f"{context}.capacity must be a finite non-negative number")
        elif isinstance(rule_type, str) and rule_type in {"C1", "C2"}:
            for side in ("a", "b"):
                action = rule.get(side)
                if not isinstance(action, dict) or not all(
                    isinstance(action.get(key), str) and action[key]
                    for key in ("target", "operation")
                ):
                    errors.append(f"{context}.{side} must define target and operation strings")
            minimum_overlap = rule.get("min_overlap_ms", 1)
            if not _is_int(minimum_overlap) or minimum_overlap < 1:
                errors.append(f"{context}.min_overlap_ms must be a positive integer")
        elif rule_type == "C4":
            task_id = rule.get("task_id")
            if not isinstance(task_id, str) or task_id not in known_tasks:
                errors.append(f"{context}.task_id must reference an episode task")
                task = {}
            else:
                task = tasks_by_id[task_id]
            conditions = rule.get("invalidating_conditions")
            if not isinstance(conditions, list) or not conditions:
                errors.append(f"{context}.invalidating_conditions must be a non-empty list")
                conditions = []
            for condition_index, condition in enumerate(conditions):
                _check_condition(condition, f"{context}.invalidating_conditions[{condition_index}]", errors)
            task_conditions = task.get("action_template", {}).get("requires", [])
            for condition in conditions:
                if condition not in task_conditions:
                    errors.append(
                        f"{context}.invalidating_conditions must appear in task_stream task_id {task_id} action_template.requires"
                    )
    if c3_count > 1:
        errors.append("conflict_rules must not define multiple C3 capacity limits")

    groundings = episode.get("action_grounding", [])
    if not isinstance(groundings, list):
        errors.append("action_grounding must be a list")
        groundings = []
    for index, grounding in enumerate(groundings):
        context = f"action_grounding[{index}]"
        if not isinstance(grounding, dict):
            errors.append(f"{context} must be an object")
            continue
        grounding_agent = grounding.get("agent_id")
        if not isinstance(grounding_agent, str) or grounding_agent not in known_agents:
            errors.append(f"{context}.agent_id must reference an episode agent")
        grounding_task = grounding.get("task_id")
        if not isinstance(grounding_task, str) or grounding_task not in known_tasks:
            errors.append(f"{context}.task_id must reference an episode task")
        if not _is_int(grounding.get("duration_ms")) or grounding["duration_ms"] < 0:
            errors.append(f"{context}.duration_ms must be a non-negative integer")
        if not _is_finite_nonnegative_number(grounding.get("power_kw")):
            errors.append(f"{context}.power_kw must be a finite non-negative number")
        for field in ("effects", "start_effects", "completion_effects", "environment_effects"):
            if field in grounding and not isinstance(grounding[field], dict):
                errors.append(f"{context}.{field} must be an object")

    return errors
