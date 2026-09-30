"""Causal, deterministic scheduling baselines for the C3 design matrix.

The coordinator receives task metadata at release and agent responses at their
ready times. It cannot inspect an action before its response has arrived.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from evaluate import ROOT, evaluate, load_json
from run_capacity_deadline_matrix import make_scenarios
from run_protocol_pilot import INSTRUCTIONS
from runtime.dry_run import DryRunClient
from runtime.execution import (
    DEVICE_DELAY_MS, _capacity_conflict_end, _synthetic_latency_ms,
    materialize_action,
)
from runtime.protocol import build_agent_request


POLICIES = (
    "ImmediateFIFO", "WaitReleasedPriority", "WaitReleasedEDF",
    "WaitReleasedPriorityCapacityAware",
)


def online_schedule(
    episode: dict, policy: str,
    latency_by_task: dict[str, int] | None = None,
    decision_by_task: dict[str, dict] | None = None,
) -> tuple[dict, dict]:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    if episode["task_family"] != "resource_capacity_conflict":
        raise ValueError("this design baseline is limited to C3 capacity episodes")
    client = DryRunClient()
    agents = {agent["agent_id"]: agent for agent in episode["agents"]}
    responses = []
    for task in episode["task_stream"]:
        agent = agents[task["agent_id"]]
        request = build_agent_request(
            episode, agent, task, architecture="ConstraintCoordinator",
            current_time_ms=task["release_at_ms"],
            current_state=deepcopy(episode["initial_state"]["values"]),
            state_version=episode["initial_state"]["version"],
            include_evaluation_hints=True,
        )
        decision = (
            decision_by_task[task["task_id"]]
            if decision_by_task is not None
            else client.decide(request, INSTRUCTIONS)
        )
        latency = (latency_by_task or {}).get(
            task["task_id"],
            _synthetic_latency_ms(episode.get("base_episode_id", episode["episode_id"]), agent["agent_id"], policy),
        )
        responses.append({
            "task": task, "agent": agent, "actions": decision.get("actions", []),
            "ready_at_ms": task["release_at_ms"] + latency,
        })
    responses.sort(key=lambda response: response["ready_at_ms"])

    events = [
        {"type": "state_update", "timestamp_ms": item["at_ms"],
         "new_state_version": item["new_state_version"], "patch": deepcopy(item.get("patch", {}))}
        for item in episode.get("exogenous_events", [])
    ]
    accepted = []
    waiting = []
    answered = set()
    now = 0
    index = 0
    capacity = float(episode["home"]["resources"]["max_power_kw"])

    while index < len(responses) or waiting:
        if not waiting and index < len(responses):
            now = max(now, responses[index]["ready_at_ms"])
        while index < len(responses) and responses[index]["ready_at_ms"] <= now:
            response = responses[index]
            answered.add(response["task"]["task_id"])
            waiting.extend((response, action) for action in response["actions"])
            index += 1
        if not waiting:
            continue

        def rank(item: tuple[dict, dict]) -> tuple:
            response, _ = item
            task = response["task"]
            if policy == "WaitReleasedEDF":
                return (task.get("completion_deadline_ms", float("inf")), -task.get("priority", 0), response["ready_at_ms"])
            if policy in {"WaitReleasedPriority", "WaitReleasedPriorityCapacityAware"}:
                return (-task.get("priority", 0), task.get("completion_deadline_ms", float("inf")), response["ready_at_ms"])
            return (response["ready_at_ms"], -task.get("priority", 0))

        chosen = min(waiting, key=rank)
        chosen_task = chosen[0]["task"]
        unseen_released = [
            task for task in episode["task_stream"]
            if task["release_at_ms"] <= now and task["task_id"] not in answered
            and task.get("completion_deadline_ms") is not None
        ]
        should_wait = policy != "ImmediateFIFO" and any(
            (task.get("completion_deadline_ms", float("inf")), -task.get("priority", 0))
            < (chosen_task.get("completion_deadline_ms", float("inf")), -chosen_task.get("priority", 0))
            if policy == "WaitReleasedEDF" else task.get("priority", 0) > chosen_task.get("priority", 0)
            for task in unseen_released
        )
        if should_wait and policy == "WaitReleasedPriorityCapacityAware":
            # Static capability bounds are known before a specialist replies;
            # the specialist's future choice remains hidden. If every possible
            # operation can overlap the ready action, waiting buys no capacity.
            chosen_action = chosen[1]
            ready_candidate = materialize_action(
                episode, chosen[0]["agent"]["agent_id"], chosen_task["task_id"],
                chosen_action, now + DEVICE_DELAY_MS,
            )
            urgent = [task for task in unseen_released
                      if task.get("priority", 0) > chosen_task.get("priority", 0)]
            max_urgent_power = sum(
                max((float(item["power_kw"]) for item in episode["action_grounding"]
                     if item.get("task_id") == task["task_id"]
                     and item.get("agent_id") == task["agent_id"]), default=0.0)
                for task in urgent
            )
            if ready_candidate["power_kw"] + max_urgent_power <= capacity:
                should_wait = False
        if should_wait and index < len(responses):
            events.append({"type": "coordination_decision", "timestamp_ms": now,
                           "decision": "wait_for_released_task", "task_id": chosen_task["task_id"]})
            now = max(now, responses[index]["ready_at_ms"])
            continue

        waiting.remove(chosen)
        response, action = chosen
        candidate = materialize_action(
            episode, response["agent"]["agent_id"], chosen_task["task_id"],
            action, max(now, response["ready_at_ms"]) + DEVICE_DELAY_MS,
        )
        while True:
            capacity_end = _capacity_conflict_end(accepted, candidate, capacity)
            if capacity_end is None:
                break
            candidate["timestamp_ms"] = max(candidate["timestamp_ms"], capacity_end)
        accepted.append(candidate)
        events.append({"type": "coordination_decision", "timestamp_ms": now,
                       "decision": "accept", "proposal_id": action["proposal_id"]})

    trace = {"trace_id": f"{episode['episode_id']}.{policy}.online",
             "episode_id": episode["episode_id"],
             "events": sorted(events + accepted, key=lambda event: event["timestamp_ms"])}
    return trace, evaluate(episode, trace)


def run(output_path: Path) -> dict:
    rows = []
    for path in sorted((ROOT / "data" / "candidates").glob("*.json")):
        source = load_json(path)
        if source["task_family"] != "resource_capacity_conflict":
            continue
        scenarios, info = make_scenarios(source)
        for scenario_name, episode in scenarios:
            for policy in POLICIES:
                trace, result = online_schedule(episode, policy)
                rows.append({
                    "source_episode": source["episode_id"], "scenario": scenario_name,
                    "policy": policy, "process_valid_success": result["process_valid_success"],
                    "timely_process_valid_success": result["timely_process_valid_success"],
                    "high_deadline_met": result["task_deadline_met"][info["high_task_id"]],
                    "first_effective_action_ms": result["first_effective_action_latency_ms"],
                    "high_action_finish_ms": result["task_action_finish_time_ms"][info["high_task_id"]],
                    "deadline_ms": next(task["completion_deadline_ms"] for task in episode["task_stream"]
                                        if task["task_id"] == info["high_task_id"]),
                    "wait_events": sum(event.get("decision") == "wait_for_released_task" for event in trace["events"]),
                })
    summary = {
        f"{scenario}.{policy}": {
            "safe": sum(row["process_valid_success"] for row in rows if row["scenario"] == scenario and row["policy"] == policy),
            "safe_and_on_time": sum(row["timely_process_valid_success"] for row in rows if row["scenario"] == scenario and row["policy"] == policy),
        }
        for scenario in ("tight_conflicting", "safe_capacity", "relaxed_deadline")
        for policy in POLICIES
    }
    payload = {"experiment": "causal_capacity_deadline_rule_baselines",
               "status": "synthetic_unreviewed_design_experiment",
               "caveat": "Agent responses are generated offline, then revealed to the coordinator only at their ready times; task metadata is visible at release. No real device or model latency is measured.",
               "summary": summary, "rows": rows}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "online_deadline_baselines_20260924.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))
