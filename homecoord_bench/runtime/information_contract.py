"""Release-filtered audit view for the controlled C3 public cost contract.

This constructs audit snapshots; controller-read independence is separately
checked with future-deletion tests. It is not an isolation sandbox.
"""
from copy import deepcopy


def released_scheduler_view(episode, now_ms, released_ids, returned_ids,
                            public_costs, committed_actions=(), announcement=None):
    tasks = {t["task_id"]: t for t in episode["task_stream"]}
    if not set(released_ids) <= set(tasks) or not set(returned_ids) <= set(released_ids):
        raise ValueError("unknown or unreleased returned task in information view")
    if any(tasks[t]["release_at_ms"] > now_ms for t in released_ids):
        raise ValueError("future task exposed before release")
    visible = []
    for task_id in sorted(released_ids):
        task = tasks[task_id]
        visible.append({k: deepcopy(task[k]) for k in
                        ("task_id", "agent_id", "release_at_ms", "completion_deadline_ms", "priority", "goal")})
        visible[-1]["declared_service_cost"] = deepcopy(public_costs[task_id])
        visible[-1]["proposal_has_returned"] = task_id in returned_ids
    committed = []
    for action in committed_actions:
        if action["task_id"] not in released_ids:
            raise ValueError("unreleased task commitment in information view")
        committed.append({k: deepcopy(action[k]) for k in
                          ("task_id", "proposal_id", "timestamp_ms", "scheduled_start_ms", "status", "duration_ms", "power_kw")})
    view = {"version": "released-public-contract-0.1", "current_time_ms": now_ms,
            "capacity_kw": episode["home"]["resources"]["max_power_kw"],
            "released_tasks": visible, "committed_actions": committed,
            "information_class": "perfect_announcement" if announcement else "released_only"}
    if announcement:
        view["announced_future_request"] = deepcopy(announcement)
    return view


def trace_information_audit(episode, events, public_costs, announcement=None):
    released, returned, commitments = set(), set(), {}
    views = []
    for event in events:
        kind = event["type"]
        if kind == "task_released":
            released.add(event["task_id"])
        elif kind == "proposal_returned":
            returned.add(event["task_id"])
        elif kind == "action_reserved":
            commitments[event["proposal_id"]] = {**event, "status": "reserved"}
        elif kind == "action_started":
            commitments[event["proposal_id"]] = {**event, "scheduled_start_ms": event["timestamp_ms"], "status": "running"}
        elif kind in ("action_completed", "action_rejected"):
            commitments.pop(event["proposal_id"], None)
        else:
            continue
        views.append(released_scheduler_view(episode, event["timestamp_ms"], released, returned,
                                              public_costs, commitments.values(), announcement))
    return views
