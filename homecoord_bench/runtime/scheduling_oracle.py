"""Exact small-instance C3 feasibility search for nonpreemptive fixed loads."""

from __future__ import annotations

import itertools
from copy import deepcopy
from typing import Any


def ideal_schedule(
    episode: dict[str, Any], *,
    now_ms: int | None = None,
    forced_starts: dict[str, int] | None = None,
    omit_task_ids: set[str] | None = None,
    extra_task: dict[str, Any] | None = None,
) -> list[dict[str, int | str]] | None:
    """Find a capacity-safe schedule or None; future is known to this oracle.

    `forced_starts` fixes already committed actions at their actual start times.
    Uncommitted work cannot begin before `now_ms`. This is an exact feasibility
    check for the small constant-load task instances, not an online policy.
    """
    omitted = omit_task_ids or set()
    tasks = {task["task_id"]: deepcopy(task) for task in episode["task_stream"]
             if task["task_id"] not in omitted}
    if extra_task is not None:
        if extra_task["task_id"] in tasks:
            raise ValueError("extra task ID collides with episode task")
        tasks[extra_task["task_id"]] = deepcopy(extra_task)
    if not tasks:
        return []
    fixed = forced_starts or {}
    if not set(fixed) <= set(tasks):
        raise ValueError("forced task is absent from oracle instance")
    for task_id, task in tasks.items():
        release = int(task["release_at_ms"])
        duration = int(task["action_template"]["duration_ms"])
        deadline = int(task["completion_deadline_ms"])
        if task_id in fixed:
            start = fixed[task_id]
            if start < release or start + duration > deadline:
                return None
            task["release_at_ms"] = start
            task["completion_deadline_ms"] = start + duration
        elif now_ms is not None:
            task["release_at_ms"] = max(release, now_ms)
            if task["release_at_ms"] + duration > deadline:
                return None
    capacity = float(episode["home"]["resources"]["max_power_kw"])
    failed: set[tuple[int, tuple[str, ...], tuple[tuple[str, int], ...]]] = set()

    def search(now: int, unstarted: tuple[str, ...],
               running: tuple[tuple[str, int], ...],
               placed: tuple[tuple[str, int, int], ...]) -> tuple[tuple[str, int, int], ...] | None:
        running = tuple((task_id, finish) for task_id, finish in running if finish > now)
        if not unstarted:
            return placed
        key = (now, unstarted, running)
        if key in failed:
            return None
        ready = [task_id for task_id in unstarted
                 if int(tasks[task_id]["release_at_ms"]) <= now]
        active_power = sum(float(tasks[task_id]["action_template"]["power_kw"])
                           for task_id, _ in running)
        # Empty subset permits waiting for a future release or completion.
        choices = [subset for count in range(len(ready), -1, -1)
                   for subset in itertools.combinations(ready, count)]
        for subset in choices:
            if active_power + sum(float(tasks[task_id]["action_template"]["power_kw"])
                                  for task_id in subset) > capacity + 1e-9:
                continue
            if any(now + int(tasks[task_id]["action_template"]["duration_ms"])
                   > int(tasks[task_id]["completion_deadline_ms"])
                   for task_id in subset):
                continue
            starts = tuple((task_id, now,
                            now + int(tasks[task_id]["action_template"]["duration_ms"]))
                           for task_id in subset)
            remaining = tuple(task_id for task_id in unstarted if task_id not in subset)
            active = running + tuple((task_id, finish) for task_id, _, finish in starts)
            if not remaining:
                return placed + starts
            next_times = [finish for _, finish in active if finish > now]
            next_times += [int(tasks[task_id]["release_at_ms"]) for task_id in remaining
                           if int(tasks[task_id]["release_at_ms"]) > now]
            if next_times:
                result = search(min(next_times), remaining, active, placed + starts)
                if result is not None:
                    return result
        failed.add(key)
        return None

    found = search(min(int(task["release_at_ms"]) for task in tasks.values()),
                   tuple(tasks), (), ())
    return ([{"task_id": task_id, "start_ms": start, "finish_ms": finish}
             for task_id, start, finish in found] if found is not None else None)
