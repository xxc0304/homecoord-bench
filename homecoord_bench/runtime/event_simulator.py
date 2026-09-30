"""Deterministic discrete-event simulator for asynchronous home coordination.

The simulator advances a virtual clock. Model calls are requested when a task
is released, then their measured or replayed latency schedules a proposal
response event. Exogenous updates and action completions continue to advance
while proposals are pending. This prototype uses a synchronous decision
provider, so actual API requests are not concurrent; replayed logical arrivals
are the supported path for controlled comparisons.
"""

from __future__ import annotations

import heapq
from time import perf_counter_ns
from copy import deepcopy
from typing import Any

from evaluate import constraints_hold, evaluate, get_path, goal_distance, set_path
from runtime.execution import (
    DEVICE_DELAY_MS,
    _condition_holds,
    _incompatible,
    _indirect_conflict,
    _overlap,
    _rule_pair_matches,
    _synthetic_latency_ms,
    materialize_action,
)
from runtime.protocol import assert_agent_decision, build_agent_request
from runtime.episode_validation import validate_event_episode
from runtime.scheduling_oracle import ideal_schedule
from runtime.tool_contract import validate_tool_call
from runtime.task_response_metrics import task_response_metrics


POLICIES = {
    "CentralSingleAgent",
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
    "CapacityAwareDeadlineCoordinator",
    "GateRetryRule",
    "FixedHoldCoordinator",
    "ObservedTaskFeasibilityCoordinator",
    "RobustReserveCoordinator",
}
POLICY_DESCRIPTIONS = {
    "CentralSingleAgent": "one globally visible agent; reserved actions are serialized",
    "IndependentMultiAgent": "specialists act without conflict or capacity coordination",
    "RuleCoordinator": "specialists with declared device locks and action-conflict rules",
    "ConstraintCoordinator": "specialists with declared state, conflict, and resource-capacity checks",
    "DeadlineAwareCoordinator": (
        "wait for responses from currently released tasks, order by earliest completion deadline "
        "then priority, and apply the same constraint and capacity checks"
    ),
    "CapacityAwareDeadlineCoordinator": (
        "wait for an earlier-deadline released proposal only when public task power bounds "
        "could make concurrent execution exceed capacity; then use constraint scheduling"
    ),
    "GateRetryRule": (
        "act on arrival; after a shared safety-gate conflict, keep the same proposal "
        "and retry at resource release using deadline-ordered constraint reservations"
    ),
    "FixedHoldCoordinator": (
        "hold released proposals until a prespecified episode clock time, then "
        "dispatch released proposals by deadline with constraint reservations"
    ),
    "ObservedTaskFeasibilityCoordinator": (
        "admit an action only if a small exact scheduler can still serve all "
        "currently released tasks; no future task metadata is used"
    ),
    "RobustReserveCoordinator": (
        "admit an action only if a small exact scheduler can still serve every "
        "released task and each declared possible urgent arrival"
    ),
}

# Heap order is (virtual time, event phase, insertion sequence). State updates
# and physical completions share the first phase; exogenous updates are queued
# before execution starts, so they precede completions at the same timestamp.
_PRIORITY_STATE_OR_COMPLETION = 0
_PRIORITY_TASK_RELEASE = 1
_PRIORITY_PROPOSAL_RESPONSE = 3
_PRIORITY_ACTION_START = 4


def _agent_by_id(episode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {agent["agent_id"]: agent for agent in episode["agents"]}


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)


def _condition_satisfied(state: dict[str, Any], condition: dict[str, Any]) -> bool:
    value = get_path(state, condition["path"])
    op, expected = condition["op"], condition["value"]
    if op == "eq": return value == expected
    if op == "neq": return value != expected
    if op == "lt": return value is not None and value < expected
    if op == "lte": return value is not None and value <= expected
    if op == "gt": return value is not None and value > expected
    if op == "gte": return value is not None and value >= expected
    if op == "between": return value is not None and expected[0] <= value <= expected[1]
    return False


def _apply_patch(state: dict[str, Any], patch: dict[str, Any]) -> None:
    for path, value in patch.items():
        set_path(state, path, deepcopy(value))


def _projected_action_state(state: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Project the state after both the start and completion effects of an action."""
    projected = deepcopy(state)
    _apply_patch(projected, candidate.get("start_effects", {}))
    _apply_patch(projected, candidate.get("effects", {}))
    return projected


def _candidate_start(episode: dict[str, Any], candidate: dict[str, Any],
                     reserved: list[dict[str, Any]], now_ms: int,
                     policy: str) -> tuple[int | None, str | None]:
    """Return the earliest online start allowed by the selected policy."""
    start = now_ms + int(episode.get("simulation", {}).get("command_latency_ms", DEVICE_DELAY_MS))
    start = max(start, candidate.get("scheduled_not_before_ms", start))
    reasons: list[str] = []
    max_iterations = 2 * (len(reserved) + 1)
    capacity = float(episode.get("home", {}).get("resources", {}).get("max_power_kw", float("inf")))

    for _ in range(max_iterations):
        changed = False
        proposed_interval = {**candidate, "timestamp_ms": start}

        if policy == "CentralSingleAgent":
            blockers = [item for item in reserved if _overlap(item, proposed_interval) > 0]
            if blockers:
                start = max(item["timestamp_ms"] + item["duration_ms"] for item in blockers)
                reasons.append("central_serialization")
                changed = True

        elif policy == "RuleCoordinator":
            blockers = [item for item in reserved
                        if item["target"] == candidate["target"]
                        and _overlap(item, proposed_interval) > 0]
            if blockers:
                start = max(item["timestamp_ms"] + item["duration_ms"] for item in blockers)
                reasons.append("device_lock")
                changed = True

        elif policy in {"ConstraintCoordinator", "DeadlineAwareCoordinator",
                        "CapacityAwareDeadlineCoordinator"}:
            c1 = [item for item in reserved
                  if _incompatible(item, candidate, episode)
                  and _overlap(item, proposed_interval) > 0]
            c2 = [item for item in reserved
                  if _indirect_conflict(item, proposed_interval, episode)]
            conflict_blockers = c1 + c2
            if conflict_blockers:
                start = max(item["timestamp_ms"] + item["duration_ms"]
                            for item in conflict_blockers)
                reasons.append("declared_action_conflict")
                changed = True

            capacity_rule = next((rule for rule in episode.get("conflict_rules", [])
                                  if rule.get("type") == "C3"), None)
            if capacity_rule:
                capacity = float(capacity_rule["capacity"])
            if candidate["power_kw"] > capacity:
                # No amount of waiting can make this action feasible by itself.
                return None, "resource_capacity_exceeded"
            for _ in range(max_iterations):
                candidate_interval = {**candidate, "timestamp_ms": start}
                boundaries = {start, start + candidate["duration_ms"]}
                for item in reserved:
                    if item["timestamp_ms"] < start + candidate["duration_ms"] and start < item["timestamp_ms"] + item["duration_ms"]:
                        boundaries.add(max(start, item["timestamp_ms"]))
                        boundaries.add(min(start + candidate["duration_ms"], item["timestamp_ms"] + item["duration_ms"]))
                shifted_to = None
                ordered = sorted(boundaries)
                for left, right in zip(ordered, ordered[1:]):
                    if right <= left:
                        continue
                    active = [item for item in reserved
                              if item["timestamp_ms"] < right
                              and item["timestamp_ms"] + item["duration_ms"] > left]
                    load = candidate["power_kw"] + sum(item["power_kw"] for item in active)
                    if load > capacity:
                        possible = [item["timestamp_ms"] + item["duration_ms"] for item in active]
                        if possible:
                            shifted_to = min(possible)
                            break
                        raise RuntimeError("capacity violation without an active reservation")
                if shifted_to is None:
                    break
                start = shifted_to
                reasons.append("resource_capacity")
                changed = True

        if not changed:
            return start, "+".join(dict.fromkeys(reasons)) or None

    raise RuntimeError("online scheduler failed to find a safe start")


def _shared_safety_gate_reason(
    episode: dict[str, Any], candidate: dict[str, Any],
    active: list[dict[str, Any]], now_ms: int,
) -> str | None:
    """Veto an unsafe start; never plan, defer, or retry an action.

    This is a common physical safety floor for policy comparisons. It only
    inspects actions already in flight and episode-declared resource limits.
    """
    interval = {**candidate, "timestamp_ms": now_ms}
    for other in active:
        if _incompatible(other, interval, episode) or _indirect_conflict(other, interval, episode):
            return "shared_gate_action_conflict"
    capacity_rule = next((rule for rule in episode.get("conflict_rules", [])
                          if rule.get("type") == "C3"), None)
    capacity = float(capacity_rule["capacity"]) if capacity_rule else float(
        episode.get("home", {}).get("resources", {}).get("max_power_kw", float("inf"))
    )
    if candidate["power_kw"] + sum(item["power_kw"] for item in active) > capacity:
        return "shared_gate_capacity"
    return None


def _legacy_evaluation_trace(episode: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    projected = []
    for event in events:
        if event["type"] == "state_update":
            # The following action_started record is projected as the single
            # state-changing action_effective event. Keeping this synthetic
            # state_update as well would apply start_effects twice and could
            # make an action appear stale against its own start transition.
            if event.get("source") == "action_started":
                continue
            projected.append({
                "type": "state_update", "timestamp_ms": event["timestamp_ms"],
                "new_state_version": event["new_state_version"],
                "patch": deepcopy(event.get("patch", {})),
            })
        elif event["type"] == "action_started":
            projected.append({
                "type": "action_effective", "timestamp_ms": event["timestamp_ms"],
                "agent_id": event["agent_id"], "task_id": event["task_id"],
                "proposal_id": event["proposal_id"], "target": event["target"],
                "operation": event["operation"], "duration_ms": event["duration_ms"],
                "power_kw": event["power_kw"],
                "based_on_state_version": event["based_on_state_version"],
                "requires": deepcopy(event["requires"]),
                "effects": deepcopy(event.get("start_effects", {})),
            })
        elif event["type"] == "action_completed":
            projected.append({
                "type": "state_update", "timestamp_ms": event["timestamp_ms"],
                "new_state_version": event["new_state_version"],
                "patch": deepcopy(event.get("effects", {})),
            })
    return {"trace_id": "event_simulator.projected", "episode_id": episode["episode_id"],
            "events": projected}


def run_event_simulation(
    episode: dict[str, Any],
    decision_provider: Any,
    policy: str,
    instructions: str,
    *,
    synthetic_latency: bool = False,
    coordination_delay_ms: int = 0,
    shared_safety_gate: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run an episode as a virtual event stream with deferred completion effects."""
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    allowed_executor = getattr(decision_provider, "allowed_execution_policies", None)
    if allowed_executor is not None and policy not in allowed_executor:
        raise ValueError("proposal adapter does not support this execution policy")
    if isinstance(coordination_delay_ms, bool) or not isinstance(coordination_delay_ms, int) or coordination_delay_ms < 0:
        raise ValueError("coordination_delay_ms must be a non-negative integer")
    if not isinstance(shared_safety_gate, bool):
        raise ValueError("shared_safety_gate must be a boolean")
    batch_compute_ms = episode.get("simulation", {}).get("released_batch_compute_ms")
    compute_profile = episode.get("simulation", {}).get("coordination_compute_profile")
    measure_compute = episode.get("simulation", {}).get("measure_coordination_compute", False)
    if not isinstance(measure_compute, bool):
        raise ValueError("measure_coordination_compute must be boolean")
    if compute_profile is not None:
        if (policy not in {"GateRetryRule", "ConstraintCoordinator", "DeadlineAwareCoordinator"}
                or coordination_delay_ms or batch_compute_ms is not None
                or episode.get("simulation", {}).get("released_batch_plan")):
            raise ValueError("ordinary compute profile requires ordinary policy without other compute delays/plans")
        if (not isinstance(compute_profile, dict)
                or set(compute_profile) != {"dispatch_ms", "retry_batch_ms"}
                or any(isinstance(v, bool) or not isinstance(v, int) or v < 0
                       for v in compute_profile.values())):
            raise ValueError("compute profile must contain non-negative integer dispatch_ms/retry_batch_ms")
    if batch_compute_ms is not None:
        if (isinstance(batch_compute_ms, bool) or not isinstance(batch_compute_ms, int)
                or batch_compute_ms < 0):
            raise ValueError("released_batch_compute_ms must be a non-negative integer")
        if (policy != "FixedHoldCoordinator"
                or not episode.get("simulation", {}).get("released_batch_plan")
                or coordination_delay_ms):
            raise ValueError("batch computation requires a FixedHold released plan and no per-action delay")
    if policy == "GateRetryRule" and not shared_safety_gate:
        raise ValueError("GateRetryRule requires the shared safety gate")
    if policy in {"RobustReserveCoordinator", "ObservedTaskFeasibilityCoordinator"} and not shared_safety_gate:
        raise ValueError(f"{policy} requires the shared safety gate")
    effective_coordination_delay_ms = (
        coordination_delay_ms
        if policy in {"RuleCoordinator", "ConstraintCoordinator", "DeadlineAwareCoordinator",
                      "CapacityAwareDeadlineCoordinator", "FixedHoldCoordinator",
                      "RobustReserveCoordinator", "ObservedTaskFeasibilityCoordinator"}
        else 0
    )
    validation_errors = validate_event_episode(episode)
    if validation_errors:
        raise ValueError("invalid event episode: " + "; ".join(validation_errors))

    queue: list[tuple[int, int, int, str, dict[str, Any]]] = []
    sequence = 0

    def push(at_ms: int, priority: int, kind: str, payload: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        heapq.heappush(queue, (int(at_ms), priority, sequence, kind, payload))

    # At equal virtual times, insertion sequence breaks ties within a phase.
    # Exogenous updates are preloaded before completions are scheduled, so they
    # apply first; both then precede task releases, proposal responses, and starts.
    for item in episode.get("exogenous_events", []):
        push(item["at_ms"], _PRIORITY_STATE_OR_COMPLETION, "exogenous_update", item)
    for task_index, task in enumerate(episode["task_stream"]):
        push(task["release_at_ms"], _PRIORITY_TASK_RELEASE, "task_release", {"task": task, "task_index": task_index})
    potential_urgent = episode.get("simulation", {}).get("potential_urgent")
    if policy == "RobustReserveCoordinator":
        if not isinstance(potential_urgent, dict) or not all(
            key in potential_urgent for key in
            ("task_id", "power_kw", "duration_ms", "deadline_ms", "possible_release_ms")
        ):
            raise ValueError("RobustReserveCoordinator requires potential_urgent metadata")
        for at_ms in potential_urgent["possible_release_ms"]:
            if not isinstance(at_ms, int) or isinstance(at_ms, bool) or at_ms < 0:
                raise ValueError("possible_release_ms must contain non-negative integers")
            push(at_ms, _PRIORITY_PROPOSAL_RESPONSE, "reserve_tick", {})
    hold_until_raw = episode.get("simulation", {}).get("hold_until_ms", 0)
    if policy == "FixedHoldCoordinator":
        if (not isinstance(hold_until_raw, int) or isinstance(hold_until_raw, bool)
                or hold_until_raw < int(episode.get("episode_release_at_ms", 0))):
            raise ValueError("hold_until_ms must be an integer at or after episode release")
        hold_until_ms = hold_until_raw
        push(hold_until_ms, _PRIORITY_PROPOSAL_RESPONSE, "hold_expiry", {})
    else:
        hold_until_ms = 0

    agents = _agent_by_id(episode)
    tasks_by_id = {task["task_id"]: task for task in episode["task_stream"]}
    central_agent = {
        "agent_id": "CentralAgent", "role": "central_home_manager",
        "objective": "Satisfy active household goals while respecting constraints.",
        "tools": sorted({tool for agent in episode["agents"] for tool in agent.get("tools", [])}),
        "observable_state": ["*"],
        "writable_resources": sorted({path for agent in episode["agents"] for path in agent.get("writable_resources", [])}),
    }
    state = deepcopy(episode["initial_state"]["values"])
    state_version = int(episode["initial_state"]["version"])
    events: list[dict[str, Any]] = []
    reservations: list[dict[str, Any]] = []
    released_task_ids: set[str] = set()
    completed_task_ids: set[str] = set()
    response_received_task_ids: set[str] = set()
    pending_proposals: dict[str, dict[str, Any]] = {}
    pending_gate_retries: dict[str, dict[str, Any]] = {}
    batch_compute_pending = False
    batch_compute_completed = False
    compute_worker_available_ms = 0
    compute_job_sequence = 0
    retry_compute_pending = False
    compute_measurements: list[dict[str, Any]] = []
    model_latencies: dict[str, int] = {}
    decisions: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    in_flight_actions: dict[str, dict[str, Any]] = {}
    in_flight_precondition_invalidations: list[dict[str, Any]] = []
    invalidated_in_flight_proposals: set[str] = set()
    unsafe_state_onsets_during_action: list[dict[str, Any]] = []
    current_time = int(episode.get("episode_release_at_ms", 0))
    agent_requests = []
    constraints = episode.get("constraints", [])
    constraint_violation_active = not constraints_hold(state, constraints)
    constraint_violation_episode_count = int(constraint_violation_active)
    constraint_violation_duration_ms = 0
    constraint_violation_started_ms = current_time if constraint_violation_active else None
    first_action_start_latency_ms: int | None = None
    first_effective_action_latency_ms: int | None = None

    def observe_constraint_state(event: dict[str, Any], at_ms: int) -> None:
        """Record entries/exits from an unsafe state interval after state changes."""
        nonlocal constraint_violation_active, constraint_violation_episode_count
        nonlocal constraint_violation_duration_ms, constraint_violation_started_ms
        invalid = not constraints_hold(state, constraints)
        if invalid and not constraint_violation_active:
            constraint_violation_episode_count += 1
            constraint_violation_started_ms = at_ms
            event["constraint_violation_started"] = True
        elif not invalid and constraint_violation_active:
            event["constraint_violation_resolved"] = True
            if constraint_violation_started_ms is not None:
                constraint_violation_duration_ms += max(0, at_ms - constraint_violation_started_ms)
            constraint_violation_started_ms = None
        constraint_violation_active = invalid

    def record_in_flight_precondition_invalidations(
        state_before_update: dict[str, Any],
        at_ms: int,
        trigger_kind: str,
        trigger_event: str,
        trigger_task_id: str | None = None,
        trigger_agent_id: str | None = None,
    ) -> None:
        """Attribute a true-to-false precondition transition to its first source."""
        for proposal_id, action in in_flight_actions.items():
            if proposal_id in invalidated_in_flight_proposals:
                continue
            newly_failed = [
                requirement for requirement in action["requires"]
                if (_condition_satisfied(state_before_update, requirement)
                    and not _condition_satisfied(state, requirement))
            ]
            if not newly_failed:
                continue
            invalidated_in_flight_proposals.add(proposal_id)
            in_flight_precondition_invalidations.append({
                "proposal_id": proposal_id,
                "task_id": action["task_id"],
                "timestamp_ms": at_ms,
                "trigger_kind": trigger_kind,
                "trigger_event": trigger_event,
                "trigger_task_id": trigger_task_id,
                "trigger_agent_id": trigger_agent_id,
                "cross_agent": (
                    trigger_agent_id is not None
                    and trigger_agent_id != action["agent_id"]
                ),
                "failed_requirements": deepcopy(newly_failed),
            })

    def measured_callback(stage: str, callback, payload, at_ms: int) -> None:
        if not measure_compute:
            callback(payload, at_ms)
            return
        started_ns = perf_counter_ns()
        callback(payload, at_ms)
        compute_measurements.append({"stage": stage, "wall_ms": (perf_counter_ns() - started_ns) / 1e6,
                                     "timestamp_ms": at_ms})

    def submit_compute(stage: str, callback, payload, at_ms: int) -> None:
        nonlocal compute_worker_available_ms, compute_job_sequence
        if compute_profile is None:
            measured_callback(stage, callback, payload, at_ms)
            return
        compute_job_sequence += 1
        started = max(at_ms, compute_worker_available_ms)
        duration = compute_profile[stage + "_ms"]
        finished = started + duration
        compute_worker_available_ms = finished
        job = {"job_id": compute_job_sequence, "stage": stage, "callback": callback,
               "data": payload, "started_at_ms": started, "duration_ms": duration}
        events.append({"type": "coordinator_job_queued", "timestamp_ms": at_ms,
                       "job_id": job["job_id"], "stage": stage,
                       "worker_queue_wait_ms": started - at_ms, "duration_ms": duration})
        push(started, _PRIORITY_PROPOSAL_RESPONSE, "ordinary_compute_started", job)
        push(finished, _PRIORITY_PROPOSAL_RESPONSE, "ordinary_compute_completed", job)

    def dispatch_proposal(response: dict[str, Any], at_ms: int) -> None:
        # Capture true proposal availability before a worker delay is charged.
        response = {**response, "proposal_ready_at_ms": response.get("proposal_ready_at_ms", at_ms)}
        submit_compute("dispatch", dispatch_proposal_body, response, at_ms)

    def dispatch_proposal_body(response: dict[str, Any], at_ms: int) -> None:
        """Validate, coordinate, and schedule a returned physical action."""
        task = response["task"]
        specialist = response["specialist"]
        agent = response["agent"]
        action = response["decision"]["actions"][0]
        authorization_error = validate_tool_call(
            episode, specialist["agent_id"], task["task_id"], action
        )
        if authorization_error:
            rejected_item = {
                "type": "action_rejected", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "agent_id": specialist["agent_id"],
                "proposal_id": action["proposal_id"], "reason": authorization_error,
            }
            events.append(rejected_item)
            rejected.append(rejected_item)
            return
        candidate = materialize_action(
            episode, specialist["agent_id"], task["task_id"], action,
            at_ms + int(episode.get("simulation", {}).get("command_latency_ms", DEVICE_DELAY_MS)),
        )
        grounding = next((item for item in episode.get("action_grounding", [])
                          if item.get("agent_id") == specialist["agent_id"]
                          and item.get("task_id") == task["task_id"]
                          and item.get("operation", "*") in {"*", action.get("operation")}), {})
        candidate["start_effects"] = deepcopy(grounding.get("start_effects", {}))
        candidate["effects"] = deepcopy(grounding.get("completion_effects", candidate.get("effects", {})))
        candidate["proposal_ready_ms"] = int(response.get("proposal_ready_at_ms", at_ms))
        candidate["specialist_agent_id"] = specialist["agent_id"]
        candidate["task_priority"] = int(task.get("priority", 0))
        released_plan = episode.get("simulation", {}).get("released_batch_plan")
        if released_plan is not None:
            if policy not in {"DeadlineAwareCoordinator", "FixedHoldCoordinator"} or released_task_ids != response_received_task_ids:
                raise ValueError("released batch plan requires all released proposals returned")
            if at_ms < released_plan["available_at_ms"] or any(t["release_at_ms"] > at_ms for t in episode["task_stream"]):
                raise ValueError("batch plan cannot use future or pending task information")
            planned = released_plan["tasks"][task["task_id"]]
            planned_start = planned["start_ms"] + (batch_compute_ms or 0)
            if planned["operation"] != action["operation"] or planned_start < at_ms:
                raise ValueError("batch plan action or clock disagrees with returned proposal")
            candidate["scheduled_not_before_ms"] = planned_start

        scheduling_policy = (
            "ConstraintCoordinator"
            if policy in {"DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
                          "FixedHoldCoordinator", "RobustReserveCoordinator",
                          "ObservedTaskFeasibilityCoordinator"}
            else policy
        )
        start, delay_reason = _candidate_start(
            episode, candidate, reservations, at_ms, scheduling_policy
        )
        if start is None:
            decision_event = {
                "type": "coordination_decision", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "proposal_id": action["proposal_id"],
                "decision": "reject", "reason": delay_reason,
            }
            rejected_item = {
                "type": "action_rejected", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "agent_id": task["agent_id"],
                "proposal_id": action["proposal_id"], "reason": delay_reason,
                "required_power_kw": candidate["power_kw"],
            }
            events.extend([decision_event, rejected_item])
            rejected.append(rejected_item)
            return
        if policy in {"RobustReserveCoordinator", "ObservedTaskFeasibilityCoordinator"} and not robust_admission_ok(
            candidate, start, at_ms
        ):
            pending_proposals[task["task_id"]] = response
            events.append({
                "type": "coordination_decision", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "proposal_id": action["proposal_id"],
                "decision": "defer", "reason": (
                    "future_viability_reservation" if policy == "RobustReserveCoordinator"
                    else "released_task_viability_reservation"
                ),
            })
            return
        candidate["timestamp_ms"] = start
        if delay_reason:
            events.append({
                "type": "coordination_decision", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "proposal_id": action["proposal_id"],
                "decision": "defer", "defer_until_ms": start,
                "reason": delay_reason,
            })
        else:
            events.append({
                "type": "coordination_decision", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "proposal_id": action["proposal_id"],
                "decision": "accept",
            })
        reservations.append(candidate)
        events.append({"type": "action_reserved", "timestamp_ms": at_ms,
                       "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
                       "scheduled_start_ms": start, "duration_ms": candidate["duration_ms"],
                       "power_kw": candidate["power_kw"]})
        push(start, _PRIORITY_ACTION_START, "action_start", {"candidate": candidate, "task": task, "agent": agent})

    def queue_or_dispatch(response: dict[str, Any], at_ms: int) -> None:
        if effective_coordination_delay_ms:
            push(at_ms + effective_coordination_delay_ms,
                 _PRIORITY_PROPOSAL_RESPONSE, "coordination_ready", {"response": response})
        else:
            dispatch_proposal(response, at_ms)

    def try_dispatch_deadline_batch(at_ms: int) -> None:
        """Wait only for proposals from tasks already released, then use EDF."""
        nonlocal batch_compute_pending
        if not pending_proposals:
            return
        outstanding = released_task_ids - response_received_task_ids
        if policy == "FixedHoldCoordinator" and at_ms < hold_until_ms:
            return
        if policy in {"DeadlineAwareCoordinator", "FixedHoldCoordinator"} and outstanding:
            return
        if batch_compute_ms is not None and not batch_compute_completed:
            if not batch_compute_pending:
                plan = episode["simulation"]["released_batch_plan"]
                if (at_ms != plan["available_at_ms"]
                        or any(t["release_at_ms"] != 0 for t in episode["task_stream"])
                        or set(pending_proposals) != set(tasks_by_id)):
                    raise ValueError("timed batch contract requires all zero-release proposals at plan availability")
                batch_compute_pending = True
                events.append({"type": "coordination_started", "timestamp_ms": at_ms,
                               "duration_ms": batch_compute_ms, "state_version": state_version,
                               "task_ids": sorted(pending_proposals),
                               "compute_scope": "public_batch_plan_only"})
                push(at_ms + batch_compute_ms, _PRIORITY_PROPOSAL_RESPONSE,
                     "batch_coordination_ready", {"started_at_ms": at_ms,
                                                  "state_version_at_compute_start": state_version})
            return
        batch = list(pending_proposals.values())
        batch.sort(key=lambda response: (
            response["task"].get("completion_deadline_ms") is None,
            response["task"].get("completion_deadline_ms", float("inf")),
            -int(response["task"].get("priority", 0)),
            response.get("proposal_ready_at_ms", at_ms),
            response["task"]["task_id"],
        ))
        if policy == "CapacityAwareDeadlineCoordinator":
            # Public rated-power upper bounds are distinct from hidden action
            # ground truth and scripted proposal templates. Unknown bounds
            # conservatively keep the later-deadline proposal pending. Include
            # earlier proposals already returned but still held in this batch;
            # omitting them can release a later task while an earlier task is
            # waiting for a third, not-yet-returned proposal.
            bounds = episode.get("home", {}).get("resources", {}).get(
                "task_power_bounds_kw", {}
            )
            capacity = float(episode.get("home", {}).get("resources", {}).get(
                "max_power_kw", float("inf")
            ))
        else:
            bounds = {}
            capacity = float("inf")
        for response in batch:
            if policy == "CapacityAwareDeadlineCoordinator":
                current = response["task"]
                current_deadline = current.get("completion_deadline_ms", float("inf"))
                earlier_ids = [
                    task_id for task_id in (outstanding | set(pending_proposals))
                    if task_id != current["task_id"]
                    and tasks_by_id[task_id].get("completion_deadline_ms", float("inf"))
                    < current_deadline
                ]
                if earlier_ids:
                    ids = [current["task_id"], *earlier_ids]
                    if any(task_id not in bounds for task_id in ids):
                        continue
                    if sum(float(bounds[task_id]) for task_id in ids) > capacity:
                        continue
            pending_proposals.pop(response["task"]["task_id"], None)
            queue_or_dispatch(response, at_ms)

    def robust_admission_ok(candidate: dict[str, Any], start: int, at_ms: int) -> bool:
        """Use identical potential-arrival metadata whether or not one occurs."""
        active_ids = released_task_ids - completed_task_ids
        variant = deepcopy(episode)
        variant["task_stream"] = [task for task in episode["task_stream"]
                                  if task["task_id"] in active_ids]
        fixed = {item["task_id"]: int(item["timestamp_ms"]) for item in reservations}
        # Opt-in service-preserving fallback. Historical episodes retain strict
        # viability admission. Only released tasks and actual commitments are
        # examined; no future-arrival metadata is used in this branch.
        if (policy == "ObservedTaskFeasibilityCoordinator"
                and episode.get("simulation", {}).get("observed_feasibility_fallback") is True
                and ideal_schedule(variant, now_ms=at_ms, forced_starts=fixed) is None):
            events.append({
                "type": "feasibility_fallback", "timestamp_ms": at_ms,
                "task_id": candidate["task_id"],
                "reason": "released_deadline_viability_already_lost",
            })
            return True
        fixed[candidate["task_id"]] = start
        options = [None]
        if policy == "RobustReserveCoordinator":
            urgent_id = potential_urgent["task_id"]
            if urgent_id not in released_task_ids:
                options = [int(release) for release in potential_urgent["possible_release_ms"]
                           if int(release) > at_ms] or [None]
        for release in options:
            extra = None
            if release is not None:
                extra = {
                    "task_id": urgent_id,
                    "release_at_ms": release,
                    "completion_deadline_ms": int(potential_urgent["deadline_ms"]),
                    "action_template": {
                        "duration_ms": int(potential_urgent["duration_ms"]),
                        "power_kw": float(potential_urgent["power_kw"]),
                    },
                }
            if ideal_schedule(variant, now_ms=at_ms, forced_starts=fixed,
                              extra_task=extra) is None:
                return False
        return True

    def try_dispatch_robust(at_ms: int) -> None:
        if policy not in {"RobustReserveCoordinator", "ObservedTaskFeasibilityCoordinator"} or not pending_proposals:
            return
        batch = sorted(pending_proposals.values(), key=lambda response: (
            response["task"].get("completion_deadline_ms", float("inf")),
            -int(response["task"].get("priority", 0)),
            response["task"]["task_id"],
        ))
        for response in batch:
            pending_proposals.pop(response["task"]["task_id"], None)
            dispatch_proposal(response, at_ms)

    def schedule_gate_retries(at_ms: int) -> None:
        nonlocal retry_compute_pending
        if policy != "GateRetryRule" or not pending_gate_retries or retry_compute_pending:
            return
        retry_compute_pending = True
        submit_compute("retry_batch", schedule_gate_retries_body, None, at_ms)

    def schedule_gate_retries_body(_payload, at_ms: int) -> None:
        """Retry saved proposals once capacity is released, without another model call."""
        nonlocal retry_compute_pending
        retry_compute_pending = False
        if policy != "GateRetryRule" or not pending_gate_retries:
            return
        batch = sorted(pending_gate_retries.values(), key=lambda item: (
            item["task"].get("completion_deadline_ms", float("inf")),
            -int(item["task"].get("priority", 0)),
            item["task"]["task_id"],
        ))
        pending_gate_retries.clear()
        for item in batch:
            candidate, task = item["candidate"], item["task"]
            start, reason = _candidate_start(
                episode, candidate, reservations, at_ms, "ConstraintCoordinator"
            )
            if start is None:
                events.append({
                    "type": "retry_abandoned", "timestamp_ms": at_ms,
                    "task_id": task["task_id"], "reason": reason,
                })
                continue
            candidate["timestamp_ms"] = start
            reservations.append(candidate)
            events.append({"type": "action_reserved", "timestamp_ms": at_ms,
                           "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
                           "scheduled_start_ms": start, "duration_ms": candidate["duration_ms"],
                           "power_kw": candidate["power_kw"]})
            events.append({
                "type": "retry_scheduled", "timestamp_ms": at_ms,
                "task_id": task["task_id"], "start_at_ms": start,
                "reason": reason,
            })
            push(start, _PRIORITY_ACTION_START, "action_start", item)

    while queue:
        now, _, _, kind, payload = heapq.heappop(queue)
        current_time = now

        if kind == "exogenous_update":
            state_before_update = deepcopy(state)
            _apply_patch(state, payload.get("patch", {}))
            state_version = max(state_version + 1, int(payload.get("new_state_version", state_version + 1)))
            event = {
                "type": "state_update", "timestamp_ms": now,
                "new_state_version": state_version, "patch": deepcopy(payload.get("patch", {})),
                "source": payload.get("event", "exogenous"),
            }
            observe_constraint_state(event, now)
            record_in_flight_precondition_invalidations(
                state_before_update, now, "exogenous_update", event["source"]
            )
            if event.get("constraint_violation_started") and in_flight_actions:
                unsafe_state_onsets_during_action.append({
                    "timestamp_ms": now,
                    "trigger_event": event["source"],
                    "active_task_ids": sorted({
                        action["task_id"] for action in in_flight_actions.values()
                    }),
                })
            events.append(event)
            continue

        if kind == "task_release":
            task = payload["task"]
            released_task_ids.add(task["task_id"])
            prepare_batch = getattr(decision_provider, "prepare_release_batch", None)
            if prepare_batch is not None:
                prepare_batch(episode, now, _state_snapshot(state), state_version, instructions)
            specialist = agents[task["agent_id"]]
            agent = central_agent if policy == "CentralSingleAgent" else specialist
            request = build_agent_request(
                episode, agent, task, architecture=policy,
                current_time_ms=now, current_state=_state_snapshot(state),
                state_version=state_version,
                include_evaluation_hints=getattr(decision_provider, "include_evaluation_hints", False),
                request_id=(
                    f"{episode.get('base_episode_id', episode['episode_id'])}:{policy}:{task['task_id']}"
                    if episode.get("simulation", {}).get("blind_future_task_arrivals", False)
                    else f"{episode['episode_id']}:{policy}:{task['task_id']}"
                ),
                released_task_ids=released_task_ids,
            )
            agent_requests.append(deepcopy(request))
            decision = decision_provider.decide(request, instructions)
            assert_agent_decision(decision)
            measured = max(1, int(round(getattr(decision_provider, "last_latency_ms", 1))))
            latency = (_synthetic_latency_ms(
                episode.get("base_episode_id", episode["episode_id"]), agent["agent_id"], policy,
                task.get("agent_id"),
            ) if synthetic_latency else measured)
            decisions[task["task_id"]] = deepcopy(decision)
            model_latencies[task["task_id"]] = latency
            push(now + latency, _PRIORITY_PROPOSAL_RESPONSE, "proposal_response", {
                "task": task, "specialist": specialist, "agent": agent,
                "decision": decision, "state_version_at_release": state_version,
                "request_id": request["request_id"], "latency_ms": latency,
            })
            events.append({
                "type": "task_released", "timestamp_ms": now,
                "task_id": task["task_id"], "agent_id": task["agent_id"],
                "state_version": state_version, "request_id": request["request_id"],
            })
            try_dispatch_robust(now)
            continue

        if kind == "proposal_response":
            task, specialist, agent = payload["task"], payload["specialist"], payload["agent"]
            decision = payload["decision"]
            events.append({
                "type": "proposal_returned", "timestamp_ms": now,
                "task_id": task["task_id"], "agent_id": task["agent_id"],
                "request_id": payload["request_id"], "latency_ms": payload["latency_ms"],
                "response_type": decision["response_type"],
            })
            if not decision.get("actions"):
                events.append({"type": "agent_no_action", "timestamp_ms": now,
                               "task_id": task["task_id"], "response_type": decision["response_type"]})
                if policy in {"DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
                              "FixedHoldCoordinator"}:
                    response_received_task_ids.add(task["task_id"])
                    try_dispatch_deadline_batch(now)
                continue
            if policy in {"DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
                          "FixedHoldCoordinator", "RobustReserveCoordinator",
                          "ObservedTaskFeasibilityCoordinator"}:
                response_received_task_ids.add(task["task_id"])
                pending_proposals[task["task_id"]] = {
                    **payload, "proposal_ready_at_ms": now,
                }
                if policy in {"RobustReserveCoordinator", "ObservedTaskFeasibilityCoordinator"}:
                    try_dispatch_robust(now)
                else:
                    try_dispatch_deadline_batch(now)
            else:
                queue_or_dispatch(payload, now)
            continue

        if kind == "coordination_ready":
            dispatch_proposal(payload["response"], now)
            continue

        if kind == "ordinary_compute_started":
            payload["state_version_at_compute_start"] = state_version
            events.append({"type": "ordinary_coordination_started", "timestamp_ms": now,
                           "job_id": payload["job_id"], "stage": payload["stage"],
                           "duration_ms": payload["duration_ms"], "state_version": state_version})
            continue

        if kind == "ordinary_compute_completed":
            events.append({"type": "ordinary_coordination_completed", "timestamp_ms": now,
                           "job_id": payload["job_id"], "stage": payload["stage"],
                           "state_version": state_version,
                           "state_changed_during_compute": state_version != payload["state_version_at_compute_start"]})
            # This calibrated-cost replay deliberately refreshes reservations
            # and state when the worker finishes, rather than committing a
            # stale schedule calculated before other jobs/updates happened.
            measured_callback(payload["stage"], payload["callback"], payload["data"], now)
            continue

        if kind == "batch_coordination_ready":
            batch_compute_completed = True
            events.append({"type": "coordination_completed", "timestamp_ms": now,
                           "started_at_ms": payload["started_at_ms"],
                           "state_version_at_compute_start": payload["state_version_at_compute_start"],
                           "state_version": state_version,
                           "state_changed_during_compute": state_version != payload["state_version_at_compute_start"],
                           "compute_scope": "public_batch_plan_only"})
            try_dispatch_deadline_batch(now)
            continue

        if kind == "hold_expiry":
            events.append({"type": "hold_expired", "timestamp_ms": now})
            try_dispatch_deadline_batch(now)
            continue

        if kind == "reserve_tick":
            events.append({"type": "reserve_tick", "timestamp_ms": now})
            try_dispatch_robust(now)
            continue

        if kind == "action_start":
            candidate, task, agent = payload["candidate"], payload["task"], payload["agent"]
            failing = [item for item in candidate["requires"] if not _condition_holds(state, item)]
            if batch_compute_ms is not None or compute_profile is not None:
                events.append({"type": "action_precondition_recheck", "timestamp_ms": now,
                               "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
                               "state_version": state_version, "passed": not failing,
                               "scope": "preconditions_only; safety gate follows"})
            if failing:
                rejected_item = {
                    "type": "action_rejected", "timestamp_ms": now,
                    "task_id": task["task_id"], "agent_id": task["agent_id"],
                    "proposal_id": candidate["proposal_id"],
                    "reason": "stale_state" if candidate["based_on_state_version"] < state_version else "unsafe_precondition",
                    "failed_requirements": deepcopy(failing),
                    "state_version": state_version,
                }
                events.append(rejected_item)
                rejected.append(rejected_item)
                reservations.remove(candidate)
                continue

            if shared_safety_gate:
                gate_reason = _shared_safety_gate_reason(
                    episode, candidate,
                    [item["candidate"] for item in in_flight_actions.values()], now,
                )
                if gate_reason:
                    event = {"type": "action_rejected", "timestamp_ms": now,
                             "task_id": task["task_id"], "agent_id": task["agent_id"],
                             "proposal_id": candidate["proposal_id"],
                             "reason": gate_reason, "state_version": state_version}
                    events.append(event)
                    rejected.append(event)
                    reservations.remove(candidate)
                    if policy == "GateRetryRule" and in_flight_actions:
                        pending_gate_retries[task["task_id"]] = payload
                        events.append({
                            "type": "retry_queued", "timestamp_ms": now,
                            "task_id": task["task_id"], "reason": gate_reason,
                        })
                    continue

            projected = deepcopy(state)
            _apply_patch(projected, candidate.get("start_effects", {}))
            if (shared_safety_gate or policy != "IndependentMultiAgent") and not constraints_hold(projected, episode.get("constraints", [])):
                event = {"type": "action_rejected", "timestamp_ms": now,
                         "task_id": task["task_id"], "agent_id": task["agent_id"],
                         "proposal_id": candidate["proposal_id"],
                         "reason": "constraint_violation", "state_version": state_version}
                events.append(event)
                rejected.append(event)
                reservations.remove(candidate)
                continue

            # The older closed-loop runner applies final effects at action
            # start. In this event simulator they happen at completion, so a
            # coordinated policy must also inspect the projected completion
            # state before allowing an irreversible physical action to start.
            # Exogenous changes during execution can still invalidate this
            # projection; that residual risk is recorded at completion below.
            if shared_safety_gate or policy != "IndependentMultiAgent":
                projected_completion = _projected_action_state(state, candidate)
                if not constraints_hold(projected_completion, episode.get("constraints", [])):
                    event = {
                        "type": "action_rejected", "timestamp_ms": now,
                        "task_id": task["task_id"], "agent_id": task["agent_id"],
                        "proposal_id": candidate["proposal_id"],
                        "reason": "predicted_completion_constraint_violation",
                        "predicted_completion_at_ms": now + candidate["duration_ms"],
                        "state_version": state_version,
                    }
                    events.append(event)
                    rejected.append(event)
                    reservations.remove(candidate)
                    continue

            state_before_start = deepcopy(state)
            before_start_distance = goal_distance(state, episode.get("goals", []))
            _apply_patch(state, candidate.get("start_effects", {}))
            after_start_distance = goal_distance(state, episode.get("goals", []))
            if (first_effective_action_latency_ms is None
                    and after_start_distance < before_start_distance
                    and constraints_hold(state, constraints)):
                first_effective_action_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
            if candidate.get("start_effects"):
                state_version += 1
                state_event = {"type": "state_update", "timestamp_ms": now,
                               "new_state_version": state_version,
                               "patch": deepcopy(candidate["start_effects"]),
                               "source": "action_started", "task_id": task["task_id"]}
                observe_constraint_state(state_event, now)
                record_in_flight_precondition_invalidations(
                    state_before_start, now, "action_started", "action_started",
                    task["task_id"], task["agent_id"],
                )
                events.append(state_event)
            started = {
                "type": "action_started", "timestamp_ms": now,
                "agent_id": task["agent_id"], "task_id": task["task_id"],
                "proposal_id": candidate["proposal_id"],
                "target": candidate["target"], "operation": candidate["operation"],
                "duration_ms": candidate["duration_ms"], "power_kw": candidate["power_kw"],
                "based_on_state_version": candidate["based_on_state_version"],
                "requires": deepcopy(candidate["requires"]),
                "start_effects": deepcopy(candidate.get("start_effects", {})),
                "completion_effects": deepcopy(candidate.get("effects", {})),
                "state_version_at_start": state_version,
            }
            if first_action_start_latency_ms is None:
                first_action_start_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
            events.append(started)
            in_flight_actions[candidate["proposal_id"]] = {
                "task_id": task["task_id"],
                "agent_id": task["agent_id"],
                "requires": deepcopy(candidate["requires"]),
                "candidate": candidate,
            }
            push(now + candidate["duration_ms"], _PRIORITY_STATE_OR_COMPLETION, "action_completion", {
                "candidate": candidate, "task": task, "agent": agent, "started_event": started,
            })
            continue

        if kind == "action_completion":
            candidate, task = payload["candidate"], payload["task"]
            state_before_completion = deepcopy(state)
            before_distance = goal_distance(state, episode.get("goals", []))
            _apply_patch(state, candidate.get("effects", {}))
            state_version += 1
            completion = {
                "type": "action_completed", "timestamp_ms": now,
                "agent_id": task["agent_id"], "task_id": task["task_id"],
                "proposal_id": candidate["proposal_id"],
                "target": candidate["target"], "operation": candidate["operation"],
                "effects": deepcopy(candidate.get("effects", {})),
                "new_state_version": state_version,
            }
            after_distance = goal_distance(state, episode.get("goals", []))
            if (first_effective_action_latency_ms is None
                    and after_distance < before_distance
                    and constraints_hold(state, constraints)):
                first_effective_action_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
            observe_constraint_state(completion, now)
            events.append(completion)
            if completion.get("constraint_violation_started"):
                completion["constraint_violation"] = True
                if in_flight_actions:
                    unsafe_state_onsets_during_action.append({
                        "timestamp_ms": now,
                        "trigger_event": "action_completed",
                        "active_task_ids": sorted({
                            action["task_id"] for action in in_flight_actions.values()
                        }),
                    })
            in_flight_actions.pop(candidate["proposal_id"], None)
            completed_task_ids.add(task["task_id"])
            if candidate.get("effects"):
                record_in_flight_precondition_invalidations(
                    state_before_completion, now, "action_completed", "action_completed",
                    task["task_id"], task["agent_id"],
                )
            reservations.remove(candidate)
            schedule_gate_retries(now)
            try_dispatch_robust(now)
            continue

        raise ValueError(f"unknown event kind: {kind}")

    # Event records are appended in heap-pop order, which already resolves
    # same-time updates/completions/releases deterministically. A timestamp-only
    # sort would lose that ordering and could replay a completion before the
    # exogenous update that actually preceded it in the event queue.
    ordered_events = events
    trace = {
        "trace_id": f"{episode['episode_id']}.{policy}.event_sim",
        "episode_id": episode["episode_id"],
        "policy": policy,
        "proposal_architecture": getattr(decision_provider, "proposal_architecture", policy),
        "events": ordered_events,
        "final_state": deepcopy(state),
        "final_state_version": state_version,
        "agent_requests": agent_requests,
    }
    projected_trace = _legacy_evaluation_trace(episode, ordered_events)
    result = evaluate(episode, projected_trace)
    completion_violations = sum(bool(event.get("constraint_violation"))
                                for event in ordered_events if event["type"] == "action_completed")
    if constraint_violation_active and constraint_violation_started_ms is not None:
        constraint_violation_duration_ms += max(0, current_time - constraint_violation_started_ms)
    rejected_preconditions = sum(event.get("reason") in {"stale_state", "unsafe_precondition"}
                                 for event in rejected)
    result.update({
        "policy": policy,
        "proposal_architecture": getattr(decision_provider, "proposal_architecture", policy),
        "proposal_count": sum(event["type"] == "proposal_returned" for event in ordered_events),
        "accepted_action_count": sum(event["type"] == "action_started" for event in ordered_events),
        "rejected_action_count": len(rejected),
        "completion_constraint_violation_count": completion_violations,
        "state_constraint_violation_episode_count": constraint_violation_episode_count,
        "state_constraint_violation_duration_ms": constraint_violation_duration_ms,
        "precondition_violations_at_start": rejected_preconditions,
        "stale_at_action_start_count": sum(
            event.get("reason") == "stale_state" for event in rejected
        ),
        "unsafe_precondition_rejection_count": sum(
            event.get("reason") == "unsafe_precondition" for event in rejected
        ),
        "in_flight_precondition_invalidated_action_count": len(
            in_flight_precondition_invalidations
        ),
        "in_flight_precondition_invalidations": in_flight_precondition_invalidations,
        "in_flight_precondition_invalidation_source_counts": {
            kind: sum(item["trigger_kind"] == kind
                      for item in in_flight_precondition_invalidations)
            for kind in ("exogenous_update", "action_started", "action_completed")
        },
        "cross_agent_in_flight_precondition_invalidated_action_count": sum(
            item["cross_agent"] for item in in_flight_precondition_invalidations
        ),
        "unsafe_state_onset_during_action_count": len(unsafe_state_onsets_during_action),
        "unsafe_state_onsets_during_action": unsafe_state_onsets_during_action,
        "process_valid_success": (result["process_valid_success"]
                                  and completion_violations == 0
                                  and constraint_violation_episode_count == 0),
        "model_latency_by_task_ms": model_latencies,
        "coordination_delay_ms": effective_coordination_delay_ms,
        "coordination_compute_measurements": compute_measurements,
        "coordination_compute_profile": deepcopy(compute_profile),
        "shared_safety_gate": shared_safety_gate,
        "shared_safety_gate_rejection_count": sum(
            event.get("reason", "").startswith("shared_gate_") for event in rejected
        ),
        "retry_queued_count": sum(event["type"] == "retry_queued" for event in ordered_events),
        "retry_scheduled_count": sum(event["type"] == "retry_scheduled" for event in ordered_events),
        "task_action_finish_time_ms": result["task_action_finish_time_ms"],
        "first_action_start_latency_ms": first_action_start_latency_ms,
        "first_goal_progress_latency_ms": first_effective_action_latency_ms,
        # Keep the historical key for existing analysis code. In this event
        # simulator it means goal progress, not the time at which a device starts.
        "first_effective_action_latency_ms": first_effective_action_latency_ms,
        "physical_completion_semantics": "final effects apply on action_completed",
        "api_calls_concurrent": False,
    })
    trace["event_count"] = len(ordered_events)
    result.update(task_response_metrics(episode, ordered_events))
    return trace, result
