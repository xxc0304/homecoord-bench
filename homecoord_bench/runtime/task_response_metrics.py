"""Per-task actual response metrics, relative to each request's own release."""
from evaluate import task_action_specs, task_accepts_action


def task_response_metrics(episode, events):
    tasks = [t for t in episode["task_stream"] if task_action_specs(t)]
    started, completed, waits, latencies, tardiness = {}, {}, {}, {}, {}
    for task in tasks:
        task_id, release = task["task_id"], task["release_at_ms"]
        starts = [e for e in events if e["type"] == "action_started"
                  and e.get("task_id") == task_id and task_accepts_action(e, task)]
        if any(e["timestamp_ms"] < release for e in starts):
            raise ValueError("correct action starts before its task release")
        finishes = [e for e in events if e["type"] == "action_completed"
                    and e.get("task_id") == task_id
                    and any(s["proposal_id"] == e.get("proposal_id") and s["timestamp_ms"] <= e["timestamp_ms"] for s in starts)]
        first_start = min((e["timestamp_ms"] for e in starts), default=None)
        first_finish = min((e["timestamp_ms"] for e in finishes), default=None)
        started[task_id], completed[task_id] = first_start is not None, first_finish is not None
        waits[task_id] = first_start - release if first_start is not None else None
        latencies[task_id] = first_finish - release if first_finish is not None else None
        deadline = task.get("completion_deadline_ms")
        tardiness[task_id] = max(0, first_finish - deadline) if first_finish is not None and deadline is not None else None
    finite_waits = [v for v in waits.values() if v is not None]
    return {
        "task_response_metric_version": "own-release-0.1",
        "task_correct_action_started": started, "task_correct_action_completed": completed,
        "task_start_wait_ms": waits, "task_completion_latency_ms": latencies,
        "task_completion_tardiness_ms": tardiness,
        "task_unstarted_count": sum(not v for v in started.values()),
        "task_incomplete_count": sum(not v for v in completed.values()),
        "max_observed_task_start_wait_ms": max(finite_waits, default=None),
        "task_start_within_1s": {t: w is not None and w <= 1000 for t, w in waits.items()},
    }
