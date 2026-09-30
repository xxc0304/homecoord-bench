"""C4 paired lifecycle replay using saved real specialist proposals.

The four event placements are fixed before model sampling. Model calls are
logical asynchronous arrivals; the device is a synthetic fixed-duration robot.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from time import perf_counter_ns

from evaluate import ROOT, load_json
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient


SOURCE = ROOT / "revision_drafts" / "20260927" / "HC-PAIR-C4-CLEAN-NO-EVENT.json"
OUTPUT = ROOT / "results" / "c4_recorded_proposal_boundary_20260928.json"
RUN_DIR = ROOT / "runs" / "c4-recorded-boundary-20260928"
POLICIES = ("IndependentMultiAgent", "RuleCoordinator",
            "ConstraintCoordinator", "DeadlineAwareCoordinator")
CONDITIONS = {
    "no_event": None,
    "precommit": 500,
    "inflight": 3000,
    "postcomplete": 6000,
}


def make_episode(condition: str) -> dict:
    if condition not in CONDITIONS:
        raise ValueError(condition)
    episode = deepcopy(load_json(SOURCE))
    episode["episode_id"] = f"HC-C4-RECORDED-{condition.upper()}"
    episode["review_status"] = "synthetic_lifecycle_probe_unreviewed"
    episode["variant"] = {"condition": condition,
                          "resident_entry_at_ms": CONDITIONS[condition]}
    entry = CONDITIONS[condition]
    episode["exogenous_events"] = [] if entry is None else [
        {"at_ms": entry, "event": "resident_enters", "patch": {"bedroom.occupied": True}},
        {"at_ms": 8000 if condition == "postcomplete" else 5000,
         "event": "resident_leaves", "patch": {"bedroom.occupied": False}},
    ]
    return episode


def _sample(client: DeepSeekResponsesClient, episode: dict, task: dict,
            repetition: int) -> dict:
    agent = next(item for item in episode["agents"] if item["agent_id"] == task["agent_id"])
    request = build_agent_request(
        episode, agent, task, architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
        request_id=f"{episode['episode_id']}:{repetition}:{task['task_id']}",
    )
    assert "required_action" not in request["task"]
    assert "action_template" not in request["task"]
    started = perf_counter_ns()
    decision = client.decide(request, PILOT_INSTRUCTIONS)
    return {"request": request, "decision": decision,
            "logical_latency_ms": max(1, round((perf_counter_ns() - started) / 1_000_000))}


def replay_row(row: dict) -> list[dict]:
    records = row["model_records"]
    output = []
    for condition in CONDITIONS:
        episode = make_episode(condition)
        ordered = [records[task["task_id"]] for task in episode["task_stream"]]
        for policy in POLICIES:
            client = MemoryReplayClient(deepcopy(ordered))
            trace, result = run_event_simulation(
                deepcopy(episode), client, policy, "recorded-proposal replay",
                shared_safety_gate=True,
            )
            client.assert_consumed()
            clean_started = next((event["timestamp_ms"] for event in trace["events"]
                                  if event["type"] == "action_started"
                                  and event["task_id"] == "bedroom_clean"), None)
            clean_completed = next((event["timestamp_ms"] for event in trace["events"]
                                    if event["type"] == "action_completed"
                                    and event["task_id"] == "bedroom_clean"), None)
            entry = CONDITIONS[condition]
            actual_phase = ("no_event" if entry is None else
                            "before_start" if clean_started is None or entry <= clean_started else
                            "in_flight" if clean_completed is None or entry < clean_completed else
                            "after_completion")
            output.append({
                "repetition": row["repetition"], "condition": condition,
                "policy": policy, "actual_entry_phase": actual_phase,
                "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                "clean_action_started_at_ms": clean_started,
                "clean_action_completed_at_ms": clean_completed,
                "final_goal_success": result["final_goal_success"],
                "process_valid_success": result["process_valid_success"],
                "task_service": result["task_service"],
                "stale_at_action_start_count": result["stale_at_action_start_count"],
                "in_flight_precondition_invalidated_action_count": result[
                    "in_flight_precondition_invalidated_action_count"
                ],
                "state_constraint_violation_duration_ms": result[
                    "state_constraint_violation_duration_ms"
                ],
                "state_constraint_violation_episode_count": result[
                    "state_constraint_violation_episode_count"
                ],
                "rejection_reasons": [event["reason"] for event in trace["events"]
                                      if event["type"] == "action_rejected"],
            })
    return output


def design() -> dict:
    return {
        "model": "deepseek-flash", "base_episode": str(SOURCE.relative_to(ROOT)),
        "event_times_ms": CONDITIONS, "policies": list(POLICIES),
        "same_model_proposals_and_logical_latencies_across_conditions_and_policies": True,
        "shared_safety_gate": True,
        "robot_duration_ms": 3000,
        "cancellation_available_in_core_simulator": False,
    }


def run(repetitions: int = 5) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if payload["design"] != design():
            raise ValueError("existing output has a different design")
    else:
        payload = {"status": "synthetic_robot_real_model_initial_proposals_no_cancellation",
                   "design": design(), "rows": [], "replays": []}
    expected = {task["task_id"] for task in make_episode("no_event")["task_stream"]}
    model = DeepSeekResponsesClient(model="deepseek-flash",
                                    logger=EventLogger(RUN_DIR / "model_events.jsonl",
                                                       "c4-recorded-boundary"))
    for repetition in range(1, repetitions + 1):
        row = next((item for item in payload["rows"] if item["repetition"] == repetition),
                   {"repetition": repetition, "model_records": {}})
        if set(row["model_records"]) == expected:
            continue
        episode = make_episode("no_event")
        for task in episode["task_stream"]:
            if task["task_id"] in row["model_records"]:
                continue
            row["model_records"][task["task_id"]] = _sample(model, episode, task, repetition)
            payload["rows"] = [item for item in payload["rows"]
                               if item["repetition"] != repetition] + [row]
            OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["replays"] = [result for item in payload["rows"]
                              if set(item.get("model_records", {})) == expected
                              for result in replay_row(item)]
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"repetition": repetition,
                          "responses": {key: record["decision"]["response_type"]
                                        for key, record in row["model_records"].items()}},
                         ensure_ascii=False), flush=True)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    report = run(args.repetitions)
    print(json.dumps({"complete_repetitions": sum(
        len(item["model_records"]) == 2 for item in report["rows"]
    ), "replays": len(report["replays"]), "output": str(OUTPUT)}, ensure_ascii=False))
