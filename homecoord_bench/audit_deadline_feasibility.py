"""Audit whether explicit task deadlines are feasible under declared workloads.

This is an optimistic lower-bound check: tasks become ready at their release
time, actions are non-preemptive, and only the episode's numeric power cap is
enforced. It does not model proposal latency, dependencies, physics, or device
feedback, so it must not be read as a deployment-time predictor.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT = ROOT / "results" / "deadline_feasibility_audit_20260926.json"


def _task_specs(episode: dict[str, Any]) -> list[dict[str, Any]]:
    groundings = {
        (item.get("task_id"), item.get("operation")): item
        for item in episode.get("action_grounding", [])
    }
    specs = []
    for task in episode.get("task_stream", []):
        template = task.get("action_template") or {}
        required = task.get("required_action") or {}
        grounding = groundings.get((task.get("task_id"), required.get("operation")), {})
        duration = template.get("duration_ms", grounding.get("duration_ms"))
        power = template.get("power_kw", grounding.get("power_kw"))
        requires = template.get("requires", [])
        specs.append({
            "task_id": task.get("task_id"),
            "release_at_ms": task.get("release_at_ms", 0),
            "completion_deadline_ms": task.get("completion_deadline_ms"),
            "duration_ms": duration,
            "power_kw": power,
            "required_action": required,
            "requires": requires,
        })
    return specs


def _schedule_order(
    tasks: list[dict[str, Any]], order: tuple[str, ...], capacity_kw: float,
) -> tuple[list[dict[str, Any]], bool]:
    by_id = {task["task_id"]: task for task in tasks}
    events: list[dict[str, Any]] = []
    individually_feasible = True
    for task_id in order:
        task = by_id[task_id]
        duration = task["duration_ms"]
        power = task["power_kw"]
        if duration is None or power is None or duration < 0 or power < 0:
            return [], False
        if power > capacity_kw:
            individually_feasible = False
            return [], False
        start = task["release_at_ms"]
        while True:
            finish = start + duration
            breakpoints = sorted({
                start,
                *(event["start_ms"] for event in events if start < event["start_ms"] < finish),
                *(event["finish_ms"] for event in events if start < event["finish_ms"] < finish),
            })
            conflict_time = None
            for point in breakpoints:
                active = [event for event in events
                          if event["start_ms"] <= point < event["finish_ms"]]
                if sum(event["power_kw"] for event in active) + power > capacity_kw:
                    conflict_time = point
                    break
            if conflict_time is None:
                break
            active = [event for event in events
                      if event["start_ms"] <= conflict_time < event["finish_ms"]]
            next_finishes = [event["finish_ms"] for event in active
                             if event["finish_ms"] > conflict_time]
            if not next_finishes:
                return [], False
            start = min(next_finishes)
        events.append({
            "task_id": task_id,
            "start_ms": start,
            "finish_ms": start + duration,
            "power_kw": power,
            "deadline_ms": task["completion_deadline_ms"],
            "deadline_met": (
                task["completion_deadline_ms"] is None
                or start + duration <= task["completion_deadline_ms"]
            ),
        })
    return events, individually_feasible


def audit_episode(episode: dict[str, Any], source: str) -> dict[str, Any] | None:
    tasks = _task_specs(episode)
    if not any(task["completion_deadline_ms"] is not None for task in tasks):
        return None
    capacity = episode.get("home", {}).get("resources", {}).get("max_power_kw")
    if not isinstance(capacity, (int, float)) or isinstance(capacity, bool) or capacity <= 0:
        return {
            "episode_id": episode.get("episode_id"),
            "source": source,
            "status": "unsupported_missing_numeric_capacity",
        }
    task_ids = [task["task_id"] for task in tasks]
    if any(task_id is None for task_id in task_ids) or len(task_ids) != len(set(task_ids)):
        return {
            "episode_id": episode.get("episode_id"),
            "source": source,
            "status": "unsupported_missing_or_duplicate_task_id",
        }
    missing = [task["task_id"] for task in tasks
               if task["duration_ms"] is None or task["power_kw"] is None]
    if missing:
        return {
            "episode_id": episode.get("episode_id"),
            "source": source,
            "status": "unsupported_missing_workload",
            "missing_workload_task_ids": missing,
        }

    deadline_count = sum(task["completion_deadline_ms"] is not None for task in tasks)
    if len(tasks) > 8:
        return {
            "episode_id": episode.get("episode_id"),
            "source": source,
            "status": "unsupported_order_space_over_8_tasks",
            "task_count": len(tasks),
            "deadline_task_count": deadline_count,
        }
    orders = list(itertools.permutations(task_ids))
    outcomes = []
    for order in orders:
        events, capacity_feasible = _schedule_order(tasks, order, float(capacity))
        outcomes.append({
            "dispatch_order": list(order),
            "capacity_feasible": capacity_feasible,
            "deadline_feasible": bool(events) and capacity_feasible and all(
                event["deadline_met"] for event in events
            ),
            "events": events,
        })
    feasible = [outcome for outcome in outcomes if outcome["deadline_feasible"]]
    capacity_only = [outcome for outcome in outcomes if outcome["capacity_feasible"]]
    if feasible:
        status = "order_sensitive" if len(feasible) < len(capacity_only) else "feasible_all_capacity_orders"
    else:
        status = "infeasible_under_declared_workload" if capacity_only else "capacity_infeasible"
    calibration = episode.get("calibration", {})
    assumptions = episode.get("physical_assumptions", {})
    calibrated = (
        calibration.get("status") == "device_calibrated"
        or assumptions.get("status") == "device_calibrated"
    )
    return {
        "episode_id": episode.get("episode_id"),
        "source": source,
        "pair_id": episode.get("pair_id"),
        "pair_condition": episode.get("pair_condition"),
        "capacity_kw": capacity,
        "task_count": len(tasks),
        "deadline_task_count": deadline_count,
        "workload_status": "device_calibrated" if calibrated else "assumed_or_unverified",
        "status": status,
        "orders_evaluated": len(orders),
        "capacity_feasible_order_count": len(capacity_only),
        "deadline_feasible_order_count": len(feasible),
        "feasible_dispatch_orders": [item["dispatch_order"] for item in feasible],
        "tasks": tasks,
        "order_outcomes": outcomes,
        "scope_limits": [
            "optimistic release-time readiness; no model proposal or network latency",
            "non-preemptive tasks; numeric aggregate power cap only",
            "does not model task dependencies, shared-environment effects, or device feedback",
            "assumed durations and powers are not physical calibration",
        ],
    }


def audit(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    rows = []
    for path in sorted(data_dir.rglob("*.json")):
        try:
            episode = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(episode, dict) or "task_stream" not in episode:
            continue
        result = audit_episode(episode, path.relative_to(data_dir).as_posix())
        if result is not None:
            rows.append(result)
    supported = [row for row in rows if row.get("status") in {
        "order_sensitive", "feasible_all_capacity_orders",
        "infeasible_under_declared_workload", "capacity_infeasible",
    }]
    return {
        "schema_version": "deadline-feasibility-audit-0.1",
        "status": "optimistic_scheduling_bound_not_runtime_prediction",
        "episode_count_with_explicit_deadlines": len(rows),
        "supported_episode_count": len(supported),
        "deadline_task_count": sum(row.get("deadline_task_count", 0) for row in rows),
        "network_calls": 0,
        "rows": rows,
        "interpretation": (
            "A deadline is treated as physically schedulable only if at least one "
            "dispatch order meets all explicit deadlines under the declared power "
            "cap and durations. This optimistic check excludes proposal latency, "
            "so it can rule out impossible cases but cannot certify online success."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = audit(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "episode_count_with_explicit_deadlines": payload["episode_count_with_explicit_deadlines"],
        "supported_episode_count": payload["supported_episode_count"],
        "deadline_task_count": payload["deadline_task_count"],
        "rows": [{
            "episode_id": row.get("episode_id"),
            "status": row.get("status"),
            "feasible_dispatch_orders": row.get("feasible_dispatch_orders", []),
            "workload_status": row.get("workload_status"),
        } for row in payload["rows"]],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
