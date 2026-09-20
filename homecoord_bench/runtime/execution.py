"""Minimal event-driven closed loop for the four seed episodes.

The simulator is intentionally small. It turns structured agent proposals into
physical events, injects exogenous state changes, and applies one of three
coordination strategies. Synthetic latency is used with DryRunClient and must
not be reported as model or device performance.
"""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter_ns
from typing import Any

from evaluate import evaluate, get_path, set_path
from runtime.protocol import build_agent_request


DEVICE_DELAY_MS = 100


def _decode_parameters(action: dict[str, Any]) -> dict[str, Any]:
    decoded = {}
    for item in action.get("parameters", []):
        decoded[item["name"]] = item["value"]
    return decoded


def _decode_requirements(action: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = []
    for item in action.get("requires", []):
        value = item["value"]
        if item["op"] == "between":
            value = [item["range_min"], item["range_max"]]
        requirements.append({"path": item["path"], "op": item["op"], "value": value})
    return requirements


def _target_name(target: str) -> str:
    return target.split(".")[-1]


def materialize_action(
    episode_or_id: dict[str, Any] | str,
    agent_id: str,
    task_id: str,
    action: dict[str, Any],
    effective_at_ms: int,
) -> dict[str, Any]:
    """Ground a permitted proposal using episode capabilities or legacy seed rules."""
    episode = episode_or_id if isinstance(episode_or_id, dict) else None
    episode_id = episode.get("base_episode_id", episode["episode_id"]) if episode else episode_or_id
    target = _target_name(action["target"])
    parameters = _decode_parameters(action)
    duration = action.get("estimated_duration_ms")
    power = action.get("estimated_power_kw")
    effects: dict[str, Any]
    operation: str

    grounding = None
    if episode:
        records = episode.get("action_grounding", [])
        grounding = next(
            (
                item for item in records
                if item.get("agent_id") == agent_id
                and item.get("task_id") == task_id
                and item.get("operation", "*") in {"*", action.get("operation")}
            ),
            None,
        )
    if grounding:
        target = _target_name(grounding.get("target", action["target"]))
        operation = grounding.get("grounded_operation", action["operation"])
        effects = deepcopy(grounding.get("effects", {}))
        actual_duration = grounding["duration_ms"]
        actual_power = grounding["power_kw"]
    else:
        key = (episode_id, agent_id, task_id)
        if key == ("HC-SEED-001", "LightingAgent", "light"):
            operation, effects = "set_reading", {"devices.study_light": "reading", "study.lux": 500}
            actual_duration, actual_power = 1000, 0.02
        elif key == ("HC-SEED-001", "ClimateAgent", "climate"):
            operation, effects = "cool", {"devices.bedroom_hvac": "cool_25", "bedroom.temperature_c": 25}
            actual_duration, actual_power = 3000, 1.2
        elif key == ("HC-SEED-002", "ComfortAgent", "comfort"):
            operation, effects = "cool", {"devices.living_hvac": "cool_24", "living_room.temperature_c": 24}
            actual_duration, actual_power = 10000, 1.4
        elif key == ("HC-SEED-002", "EnergyAgent", "energy"):
            mode = parameters.get("mode") or parameters.get("state")
            if action["operation"] == "off" or mode == "off":
                operation, effects = "off", {"devices.living_hvac": "forced_off"}
                actual_duration, actual_power = 1000, 0.0
            else:
                operation, effects = "cool", {"devices.living_hvac": "cool_24", "living_room.temperature_c": 24}
                actual_duration, actual_power = 10000, 1.2
        elif key == ("HC-SEED-003", "AirQualityAgent", "air"):
            operation, effects = "open", {"devices.window": "open", "living_room.co2_ppm": 900}
            actual_duration, actual_power = 2000, 0.0
        elif key == ("HC-SEED-003", "ClimateAgent", "heat"):
            operation, effects = "heat_high", {"devices.heater": "high", "living_room.temperature_c": 21}
            actual_duration, actual_power = 3000, 2.0
        elif key == ("HC-SEED-004", "CleaningAgent", "clean"):
            operation, effects = "clean", {"devices.robot": "complete", "living_room.clean": True}
            actual_duration, actual_power = 3000, 0.2
        elif key == ("HC-SEED-004", "CareAgent", "care"):
            operation, effects = "observe", {}
            actual_duration, actual_power = 100, 0.0
        else:
            raise ValueError(f"proposal cannot be grounded: {key}")

    return {
        "type": "action_effective",
        "timestamp_ms": effective_at_ms,
        "agent_id": agent_id,
        "task_id": task_id,
        "proposal_id": action["proposal_id"],
        "target": target,
        "operation": operation,
        "duration_ms": actual_duration,
        "power_kw": actual_power,
        "proposed_duration_ms": duration,
        "proposed_power_kw": power,
        "based_on_state_version": action["based_on_state_version"],
        "requires": _decode_requirements(action),
        "effects": effects,
    }


def _apply_patch(state: dict[str, Any], patch: dict[str, Any]) -> None:
    for path, value in patch.items():
        set_path(state, path, value)


def _condition_holds(state: dict[str, Any], requirement: dict[str, Any]) -> bool:
    actual = get_path(state, requirement["path"])
    expected = requirement["value"]
    op = requirement["op"]
    if op == "eq": return actual == expected
    if op == "neq": return actual != expected
    if op == "lt": return actual is not None and actual < expected
    if op == "lte": return actual is not None and actual <= expected
    if op == "gt": return actual is not None and actual > expected
    if op == "gte": return actual is not None and actual >= expected
    if op == "between": return actual is not None and expected[0] <= actual <= expected[1]
    return False


def _rule_pair_matches(first: dict[str, Any], second: dict[str, Any], rule: dict[str, Any]) -> bool:
    return (
        (first["target"], first["operation"]) == (rule["a"]["target"], rule["a"]["operation"])
        and (second["target"], second["operation"]) == (rule["b"]["target"], rule["b"]["operation"])
    ) or (
        (second["target"], second["operation"]) == (rule["a"]["target"], rule["a"]["operation"])
        and (first["target"], first["operation"]) == (rule["b"]["target"], rule["b"]["operation"])
    )


def _incompatible(first: dict[str, Any], second: dict[str, Any], episode: dict[str, Any] | None = None) -> bool:
    if episode:
        return any(
            rule.get("type") == "C1" and _rule_pair_matches(first, second, rule)
            for rule in episode.get("conflict_rules", [])
        )
    return first["target"] == second["target"] and {first["operation"], second["operation"]} == {"cool", "off"}


def _overlap(first: dict[str, Any], second: dict[str, Any]) -> int:
    return max(0, min(first["timestamp_ms"] + first["duration_ms"], second["timestamp_ms"] + second["duration_ms"]) - max(first["timestamp_ms"], second["timestamp_ms"]))


def _indirect_conflict(first: dict[str, Any], second: dict[str, Any], episode: dict[str, Any] | None = None) -> bool:
    if episode:
        return any(
            rule.get("type") == "C2"
            and _rule_pair_matches(first, second, rule)
            and _overlap(first, second) >= rule.get("min_overlap_ms", 1)
            for rule in episode.get("conflict_rules", [])
        )
    pair = {(first["target"], first["operation"]), (second["target"], second["operation"])}
    return pair == {("window", "open"), ("heater", "heat_high")} and _overlap(first, second) >= 1000


def _capacity_conflict_end(accepted: list[dict[str, Any]], candidate: dict[str, Any], capacity_kw: float) -> int | None:
    overlapping = [event for event in accepted if _overlap(event, candidate) > 0]
    if candidate.get("power_kw", 0) + sum(event.get("power_kw", 0) for event in overlapping) <= capacity_kw:
        return None
    return max(event["timestamp_ms"] + event["duration_ms"] for event in overlapping)


def _synthetic_latency_ms(episode_id: str, agent_id: str, architecture: str, task_agent_id: str | None = None) -> int:
    effective_role = task_agent_id or agent_id
    if episode_id == "HC-SEED-004" and effective_role == "CleaningAgent":
        base = 1700
    else:
        base = 600
    return base + (300 if architecture == "CentralSingleAgent" else 0)


def _state_at(episode: dict[str, Any], events: list[dict[str, Any]], timestamp_ms: int) -> tuple[dict[str, Any], int]:
    state = deepcopy(episode["initial_state"]["values"])
    version = episode["initial_state"]["version"]
    for event in sorted(events, key=lambda item: (item["timestamp_ms"], 0 if item["type"] == "state_update" else 1)):
        if event["timestamp_ms"] > timestamp_ms:
            break
        _apply_patch(state, event.get("patch", event.get("effects", {})))
        version = event.get("new_state_version", version)
    return state, version


def _recovery_event(episode: dict[str, Any], rejected_item: dict[str, Any]) -> dict[str, Any] | None:
    """Find the first exogenous event that satisfies a task's recovery wake condition."""
    task = rejected_item["task"]
    recovery = task.get("recovery")
    if recovery is None and task.get("task_id") == "clean":
        # Backward-compatible default for the original seed episode.
        recovery = {"wake_condition": {"path": "living_room.occupied", "op": "eq", "value": False}}
    if not recovery or not recovery.get("wake_condition"):
        return None
    condition = recovery["wake_condition"]
    for item in sorted(episode.get("exogenous_events", []), key=lambda event: event["at_ms"]):
        if item["at_ms"] <= rejected_item["ready_at_ms"]:
            continue
        state, _ = _state_at(episode, [
            {
                "type": "state_update",
                "timestamp_ms": event["at_ms"],
                "new_state_version": event["new_state_version"],
                "patch": event.get("patch", {}),
            }
            for event in episode.get("exogenous_events", [])
        ], item["at_ms"])
        if _condition_holds(state, condition):
            return item
    return None


def _call_agent(client: Any, request: dict[str, Any], instructions: str, synthetic: bool, architecture: str) -> tuple[dict[str, Any], int]:
    started = perf_counter_ns()
    decision = client.decide(request, instructions)
    measured = max(1, round((perf_counter_ns() - started) / 1_000_000))
    latency = _synthetic_latency_ms(
        request.get("base_episode_id", request["episode_id"]),
        request["agent"]["agent_id"],
        architecture,
        request.get("task", {}).get("agent_id"),
    ) if synthetic else getattr(client, "last_latency_ms", measured)
    return decision, latency


def run_closed_loop_episode(
    episode: dict[str, Any],
    client: Any,
    architecture: str,
    instructions: str,
    *,
    synthetic_latency: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if architecture not in {"CentralSingleAgent", "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator"}:
        raise ValueError(f"unsupported architecture: {architecture}")

    events: list[dict[str, Any]] = [
        {
            "type": "state_update",
            "timestamp_ms": item["at_ms"],
            "new_state_version": item["new_state_version"],
            "patch": deepcopy(item.get("patch", {})),
        }
        for item in episode.get("exogenous_events", [])
    ]
    proposals: list[dict[str, Any]] = []
    agent_by_id = {item["agent_id"]: item for item in episode["agents"]}
    central_agent = {
        "agent_id": "CentralAgent",
        "role": "central_home_manager",
        "objective": "Satisfy active household goals while respecting all constraints.",
        "tools": sorted({tool for item in episode["agents"] for tool in item.get("tools", [])}),
        "observable_state": ["*"],
        "writable_resources": sorted({resource for item in episode["agents"] for resource in item.get("writable_resources", [])}),
        "policy_constraints": ["all_episode_constraints"],
    }

    for task in episode["task_stream"]:
        specialist = agent_by_id[task["agent_id"]]
        agent = central_agent if architecture == "CentralSingleAgent" else specialist
        state, version = _state_at(episode, events, task["release_at_ms"])
        request = build_agent_request(
            episode,
            agent,
            task,
            architecture=architecture,
            current_time_ms=task["release_at_ms"],
            current_state=state,
            state_version=version,
        )
        decision, latency = _call_agent(client, request, instructions, synthetic_latency, architecture)
        for action in decision.get("actions", []):
            ready_at = task["release_at_ms"] + latency
            proposals.append({
                "task": task,
                "agent": agent,
                "specialist_agent_id": specialist["agent_id"],
                "action": action,
                "ready_at_ms": ready_at,
                "model_latency_ms": latency,
            })

    proposals.sort(key=lambda item: (item["ready_at_ms"], -item["task"].get("priority", 0)))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    serial_cursor = 0

    for proposal_index, proposal in enumerate(proposals):
        task, agent, action = proposal["task"], proposal["agent"], proposal["action"]
        effective_at = proposal["ready_at_ms"] + DEVICE_DELAY_MS
        if architecture == "CentralSingleAgent":
            effective_at = max(effective_at, serial_cursor + DEVICE_DELAY_MS)
        candidate = materialize_action(episode, proposal["specialist_agent_id"], task["task_id"], action, effective_at)
        if architecture == "CentralSingleAgent":
            candidate["agent_id"] = "CentralAgent"
        state, current_version = _state_at(episode, events + accepted, effective_at)
        stale = action["based_on_state_version"] < current_version and any(
            not _condition_holds(state, requirement) for requirement in candidate["requires"]
        )
        direct = next((
            old for old in accepted
            if _incompatible(old, candidate, episode)
            and (architecture == "CentralSingleAgent" or _overlap(old, candidate) > 0)
        ), None)
        pending_higher_priority = None
        if architecture != "IndependentMultiAgent":
            for pending in proposals[proposal_index + 1:]:
                if pending["task"].get("priority", 0) <= task.get("priority", 0):
                    continue
                pending_event = materialize_action(
                    episode,
                    pending["specialist_agent_id"],
                    pending["task"]["task_id"],
                    pending["action"],
                    pending["ready_at_ms"] + DEVICE_DELAY_MS,
                )
                if _incompatible(candidate, pending_event, episode):
                    pending_higher_priority = pending
                    break

        reason = None
        if architecture != "IndependentMultiAgent" and stale:
            reason = "stale_state"
        elif pending_higher_priority:
            reason = "priority_resolution"
        elif architecture != "IndependentMultiAgent" and direct:
            old_priority = next((p["task"].get("priority", 0) for p in proposals if p["action"]["proposal_id"] == direct["proposal_id"]), 0)
            if task.get("priority", 0) <= old_priority:
                reason = "priority_resolution"
        elif architecture == "CentralSingleAgent" and any(_indirect_conflict(old, candidate, episode) for old in accepted):
            latest_end = max(
                old["timestamp_ms"] + old["duration_ms"]
                for old in accepted
                if _indirect_conflict(old, candidate, episode)
            )
            candidate["timestamp_ms"] = latest_end

        delay_reason = None
        if architecture == "ConstraintCoordinator" and reason is None:
            indirect = [old for old in accepted if _indirect_conflict(old, candidate, episode)]
            if indirect:
                candidate["timestamp_ms"] = max(old["timestamp_ms"] + old["duration_ms"] for old in indirect)
                delay_reason = "indirect_environment_conflict"
            capacity_end = _capacity_conflict_end(
                accepted,
                candidate,
                float(episode.get("home", {}).get("resources", {}).get("max_power_kw", float("inf"))),
            )
            if capacity_end is not None:
                candidate["timestamp_ms"] = max(candidate["timestamp_ms"], capacity_end)
                delay_reason = "resource_capacity_conflict"

        if reason:
            rejected.append({**proposal, "reason": reason})
            events.append({"type": "coordination_decision", "timestamp_ms": proposal["ready_at_ms"], "decision": "reject", "proposal_id": action["proposal_id"], "reason": reason})
            continue

        if architecture != "IndependentMultiAgent":
            coordination_event = {"type": "coordination_decision", "timestamp_ms": proposal["ready_at_ms"], "decision": "accept", "proposal_id": action["proposal_id"]}
            if delay_reason:
                coordination_event["reason"] = delay_reason
                coordination_event["defer_until_ms"] = candidate["timestamp_ms"]
            events.append(coordination_event)
        accepted.append(candidate)
        if architecture == "CentralSingleAgent":
            serial_cursor = candidate["timestamp_ms"] + candidate["duration_ms"]

    # A stale proposal can opt into a local recovery wake-up. One explicit defer
    # is followed so that a valid recovery is not lost merely because the first
    # retry asks for a later wake-up. The legacy cleaning seed keeps its default.
    for rejected_item in list(rejected):
        if rejected_item["reason"] != "stale_state":
            continue
        future = _recovery_event(episode, rejected_item)
        if not future:
            continue
        retry_at = future["at_ms"]
        for retry_index in range(2):
            state, version = _state_at(episode, events + accepted, retry_at)
            request = build_agent_request(
                episode,
                rejected_item["agent"],
                rejected_item["task"],
                architecture=architecture,
                current_time_ms=retry_at,
                current_state=state,
                state_version=version,
            )
            decision, latency = _call_agent(client, request, instructions, synthetic_latency, architecture)
            decision_at = retry_at + latency
            if decision.get("actions"):
                action = decision["actions"][0]
                event = materialize_action(
                    episode, rejected_item["specialist_agent_id"], rejected_item["task"]["task_id"], action,
                    decision_at + DEVICE_DELAY_MS,
                )
                if architecture == "CentralSingleAgent":
                    event["agent_id"] = "CentralAgent"
                events.append({"type": "coordination_decision", "timestamp_ms": decision_at, "decision": "accept_retry", "proposal_id": action["proposal_id"]})
                accepted.append(event)
                break
            defer_until = decision.get("defer_until_ms")
            if retry_index == 0 and defer_until is not None and defer_until > retry_at:
                events.append({
                    "type": "coordination_decision",
                    "timestamp_ms": decision_at,
                    "decision": "defer_retry",
                    "defer_until_ms": defer_until,
                    "reason": decision.get("reason_code"),
                })
                retry_at = max(defer_until, decision_at)
                continue
            break

    trace = {
        "trace_id": f"{episode['episode_id']}.{architecture}.closed_loop",
        "episode_id": episode["episode_id"],
        "events": sorted(events + accepted, key=lambda item: (item["timestamp_ms"], 0 if item["type"] == "state_update" else 1)),
    }
    result = evaluate(episode, trace)
    result.update({
        "architecture": architecture,
        "proposal_count": len(proposals),
        "accepted_action_count": len(accepted),
        "rejected_action_count": len(rejected),
        "synthetic_latency": synthetic_latency,
    })
    return trace, result
