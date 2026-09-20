"""Deterministic evaluator for the HomeCoord-Bench seed episodes."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent


def get_path(state: dict[str, Any], path: str) -> Any:
    current: Any = state
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def set_path(state: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    current = state
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value


def predicate(value: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return value == expected
    if operator == "neq":
        return value != expected
    if operator == "lt":
        return value is not None and value < expected
    if operator == "lte":
        return value is not None and value <= expected
    if operator == "gt":
        return value is not None and value > expected
    if operator == "gte":
        return value is not None and value >= expected
    if operator == "between":
        return value is not None and expected[0] <= value <= expected[1]
    raise ValueError(f"Unsupported operator: {operator}")


def condition_holds(state: dict[str, Any], condition: dict[str, Any]) -> bool:
    return predicate(get_path(state, condition["path"]), condition["op"], condition["value"])


def goals_satisfied(state: dict[str, Any], goals: list[dict[str, Any]]) -> bool:
    return all(condition_holds(state, goal) for goal in goals)


def goal_distance(state: dict[str, Any], goals: list[dict[str, Any]]) -> float:
    """A small deterministic progress measure; lower is better."""
    total = 0.0
    for goal in goals:
        value = get_path(state, goal["path"])
        expected = goal["value"]
        op = goal["op"]
        if condition_holds(state, goal):
            continue
        if isinstance(value, (int, float)) and op == "between":
            total += min(abs(value - expected[0]), abs(value - expected[1]))
        elif isinstance(value, (int, float)) and isinstance(expected, (int, float)):
            total += abs(value - expected)
        else:
            total += 1.0
    return total


def interval(event: dict[str, Any]) -> tuple[int, int]:
    start = event["timestamp_ms"]
    return start, start + event.get("duration_ms", 0)


def overlap_ms(a: dict[str, Any], b: dict[str, Any]) -> int:
    a0, a1 = interval(a)
    b0, b1 = interval(b)
    return max(0, min(a1, b1) - max(a0, b0))


def action_matches(event: dict[str, Any], spec: dict[str, Any]) -> bool:
    return all(event.get(key) == value for key, value in spec.items())


def constraints_hold(state: dict[str, Any], constraints: list[dict[str, Any]]) -> bool:
    for rule in constraints:
        when = rule.get("when", [])
        must = rule.get("must", [])
        if all(condition_holds(state, item) for item in when):
            if not all(condition_holds(state, item) for item in must):
                return False
    return True


def validate_episode_shape(episode: dict[str, Any]) -> list[str]:
    required = {
        "episode_id", "task_family", "episode_release_at_ms", "home",
        "initial_state", "agents", "task_stream", "goals", "constraints",
        "conflict_rules",
    }
    errors = [f"missing field: {key}" for key in sorted(required - episode.keys())]
    if len(episode.get("agents", [])) < 2:
        errors.append("episode must contain at least two agents")
    if len(episode.get("task_stream", [])) < 2:
        errors.append("episode must contain at least two asynchronous tasks")
    agent_ids = {agent.get("agent_id") for agent in episode.get("agents", [])}
    for index, task in enumerate(episode.get("task_stream", [])):
        if task.get("agent_id") not in agent_ids:
            errors.append(f"task_stream[{index}].agent_id must reference an episode agent")
    if not isinstance(episode.get("initial_state", {}).get("version"), int):
        errors.append("initial_state.version must be an integer")
    return errors


def evaluate(episode: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    if trace.get("episode_id") != episode.get("episode_id"):
        raise ValueError("trace episode_id does not match episode")
    shape_errors = validate_episode_shape(episode)
    if shape_errors:
        raise ValueError("; ".join(shape_errors))

    state = deepcopy(episode["initial_state"]["values"])
    version = episode["initial_state"]["version"]
    release = episode["episode_release_at_ms"]
    goals = episode["goals"]
    constraints = episode["constraints"]
    events = sorted(trace["events"], key=lambda item: (item["timestamp_ms"], item.get("sequence", 0)))
    actions: list[dict[str, Any]] = []
    violations = 0
    stale_actions = 0
    first_effective: int | None = None
    completion: int | None = release if goals_satisfied(state, goals) else None
    first_coordination: int | None = None

    for event in events:
        kind = event["type"]
        if kind == "coordination_decision":
            if first_coordination is None:
                first_coordination = event["timestamp_ms"]
            continue
        if kind == "state_update":
            for path, value in event.get("patch", {}).items():
                set_path(state, path, value)
            version = event.get("new_state_version", version + 1)
        elif kind == "action_effective":
            before = goal_distance(state, goals)
            stale = False
            if event.get("based_on_state_version", version) < version:
                stale = any(not condition_holds(state, req) for req in event.get("requires", []))
            if stale:
                stale_actions += 1
            for path, value in event.get("effects", {}).items():
                set_path(state, path, value)
            after = goal_distance(state, goals)
            valid_now = constraints_hold(state, constraints)
            if first_effective is None and after < before and valid_now:
                first_effective = event["timestamp_ms"]
            if not valid_now:
                violations += 1
            actions.append(event)
        else:
            raise ValueError(f"Unsupported event type: {kind}")

        if completion is None and goals_satisfied(state, goals):
            completion = event["timestamp_ms"]

    counts = {"C1": 0, "C2": 0, "C3": 0, "C4": stale_actions}
    for rule in episode["conflict_rules"]:
        category = rule["type"]
        if category == "C1":
            for index, first in enumerate(actions):
                for second in actions[index + 1:]:
                    if (action_matches(first, rule["a"]) and action_matches(second, rule["b"])) or (
                        action_matches(first, rule["b"]) and action_matches(second, rule["a"])
                    ):
                        if overlap_ms(first, second) >= rule.get("min_overlap_ms", 1):
                            counts["C1"] += 1
        elif category == "C2":
            left = [event for event in actions if action_matches(event, rule["a"])]
            right = [event for event in actions if action_matches(event, rule["b"])]
            counts["C2"] += sum(
                overlap_ms(a, b) >= rule["min_overlap_ms"] for a in left for b in right
            )
        elif category == "C3":
            points = sorted({point for event in actions for point in interval(event)})
            capacity = rule["capacity"]
            for start, end in zip(points, points[1:]):
                if end <= start:
                    continue
                power = sum(
                    event.get("power_kw", 0)
                    for event in actions
                    if interval(event)[0] < end and interval(event)[1] > start
                )
                if power > capacity:
                    counts["C3"] += 1
                    break

    final_success = goals_satisfied(state, goals)
    process_valid = final_success and violations == 0 and sum(counts.values()) == 0
    serviceable_tasks = [task for task in episode["task_stream"] if task.get("required_action")]
    task_service = {
        task["task_id"]: any(
            (
                event.get("task_id") == task["task_id"]
                or (event.get("task_id") is None and event.get("agent_id") == task["agent_id"])
            )
            and action_matches(event, task["required_action"])
            for event in actions
        )
        for task in serviceable_tasks
    }
    served_task_count = sum(task_service.values())
    return {
        "episode_id": episode["episode_id"],
        "trace_id": trace["trace_id"],
        "final_goal_success": final_success,
        "process_valid_success": process_valid,
        "constraint_violation_count": violations,
        "conflict_counts": counts,
        "stale_action_count": stale_actions,
        "first_effective_action_latency_ms": None if first_effective is None else first_effective - release,
        "task_completion_time_ms": None if completion is None else completion - release,
        "coordination_decision_latency_ms": None if first_coordination is None else first_coordination - release,
        "task_service": task_service,
        "served_task_count": served_task_count,
        "serviceable_task_count": len(serviceable_tasks),
        "task_service_rate": served_task_count / len(serviceable_tasks) if serviceable_tasks else None,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_cases() -> Iterable[tuple[Path, Path]]:
    for trace_path in sorted((ROOT / "traces").glob("*.json")):
        trace = load_json(trace_path)
        yield ROOT / "data" / "seeds" / f"{trace['episode_id']}.json", trace_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.all:
        results = [evaluate(load_json(ep), load_json(tr)) for ep, tr in iter_cases()]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.episode and args.trace:
        print(json.dumps(evaluate(load_json(args.episode), load_json(args.trace)), ensure_ascii=False, indent=2))
    else:
        parser.error("use --all or provide both --episode and --trace")


if __name__ == "__main__":
    main()
