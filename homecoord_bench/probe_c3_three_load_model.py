"""Real DeepSeek proposals, logically asynchronous replay for three C3 tasks."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from time import perf_counter_ns

from evaluate import ROOT
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from probe_c3_three_load import POLICIES, make_episode
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient


OUTPUT = ROOT / "results" / "c3_three_load_model_pilot_20260928.json"
RUN_DIR = ROOT / "runs" / "c3-three-load-model-20260928"


def sample_one(client: DeepSeekResponsesClient, episode: dict,
               task: dict, repetition: int) -> dict:
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


def replay_records(records_by_task: dict[str, dict], repetition: int) -> list[dict]:
    rows = []
    for condition in ("conflict", "control"):
        episode = make_episode(condition)
        ordered = [records_by_task[task["task_id"]] for task in episode["task_stream"]]
        for policy in POLICIES:
            client = MemoryReplayClient(deepcopy(ordered))
            trace, result = run_event_simulation(
                deepcopy(episode), client, policy, "recorded-proposal replay",
                shared_safety_gate=True,
            )
            client.assert_consumed()
            rows.append({
                "repetition": repetition, "condition": condition, "policy": policy,
                "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                "response_type_by_task": {
                    task["task_id"]: record["decision"]["response_type"]
                    for task, record in zip(episode["task_stream"], ordered)
                },
                "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                "task_service": result["task_service"],
                "task_deadline_met": result["task_deadline_met"],
                "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                "all_deadlines_met": result["all_deadlines_met"],
                "final_goal_success": result["final_goal_success"],
                "process_valid_success": result["process_valid_success"],
                "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                "rejection_reasons": [event["reason"] for event in trace["events"]
                                      if event["type"] == "action_rejected"],
                "start_order": [event["task_id"] for event in trace["events"]
                                if event["type"] == "action_started"],
            })
    return rows


def design() -> dict:
    return {"model": "deepseek-flash", "task_template": "c3_three_load_v0.1",
            "same_proposals_and_logical_latencies_across_conditions_and_policies": True,
            "same_shared_safety_gate": True,
            "policies": list(POLICIES),
            "scenarios": {condition: make_episode(condition)
                          for condition in ("conflict", "control")}}


def run(repetitions: int = 5) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if payload["design"] != design():
            raise ValueError("existing output uses a different scenario or policy design")
    else:
        payload = {"status": "synthetic_fixed_cycle_assumptions_real_model_proposals",
                   "design": design(), "rows": [], "replays": []}
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "c3-three-load-model")
    model = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    expected_ids = {task["task_id"] for task in make_episode("conflict")["task_stream"]}
    for repetition in range(1, repetitions + 1):
        row = next((item for item in payload["rows"] if item["repetition"] == repetition),
                   {"repetition": repetition, "model_records": {}})
        if set(row["model_records"]) == expected_ids:
            continue
        episode = make_episode("conflict")
        for task in episode["task_stream"]:
            if task["task_id"] in row["model_records"]:
                continue
            row["model_records"][task["task_id"]] = sample_one(model, episode, task, repetition)
            payload["rows"] = [item for item in payload["rows"]
                               if item["repetition"] != repetition] + [row]
            OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["replays"] = [result for item in payload["rows"]
                              if set(item.get("model_records", {})) == expected_ids
                              for result in replay_records(item["model_records"], item["repetition"])]
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
        len(item["model_records"]) == 3 for item in report["rows"]
    ), "replays": len(report["replays"]), "output": str(OUTPUT)}, ensure_ascii=False))
