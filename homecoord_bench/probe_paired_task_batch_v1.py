"""Exploratory real-model probe for the new paired C1 and C3 tasks.

No device is controlled. For each pair, the local specialist proposal is
sampled once and reused across both environmental conditions; the conditional
specialist is sampled separately where its visible state changes.
"""

from __future__ import annotations

import argparse
import json
from time import perf_counter_ns

from evaluate import ROOT
from make_paired_task_batch_v1 import build_batch
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.execution import run_closed_loop_episode
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient


RUN_DIR = ROOT / "runs" / "paired_task_batch_v1_probe"
OUTPUT = ROOT / "results" / "paired_task_batch_v1_probe.json"
PAIRS = ("C1-HVAC", "C1-BLINDS", "C3-EV-WATER")


def _sample(client: DeepSeekResponsesClient, episode: dict, task_index: int) -> dict:
    task = episode["task_stream"][task_index]
    agent = next(item for item in episode["agents"] if item["agent_id"] == task["agent_id"])
    request = build_agent_request(
        episode, agent, task, architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
    )
    assert "required_action" not in request["task"] and "action_template" not in request["task"]
    started = perf_counter_ns()
    decision = client.decide(request, PILOT_INSTRUCTIONS)
    return {"request": request, "decision": decision,
            "logical_latency_ms": max(1, round((perf_counter_ns() - started) / 1_000_000))}


def _replay(episode: dict, records: list[dict]) -> dict:
    outcomes = {}
    for architecture in ("IndependentMultiAgent", "ConstraintCoordinator"):
        replay = MemoryReplayClient(records)
        trace, result = run_closed_loop_episode(
            episode, replay, architecture, PILOT_INSTRUCTIONS, synthetic_latency=False
        )
        replay.assert_consumed()
        outcomes[architecture] = {
            "final_goal_success": result["final_goal_success"],
            "process_valid_success": result["process_valid_success"],
            "conflict_counts": result["conflict_counts"],
            "task_service": result["task_service"],
            "task_action_finish_time_ms": result["task_action_finish_time_ms"],
            "task_deadline_met": result["task_deadline_met"],
            "first_action_ms": result["first_effective_action_latency_ms"],
            "goal_first_satisfied_ms": result["task_completion_time_ms"],
            "accepted_action_count": result["accepted_action_count"],
            "rejected_action_count": result["rejected_action_count"],
            "rejection_reasons": [event.get("reason") for event in trace["events"]
                                  if event["type"] == "coordination_decision"
                                  and event.get("decision") == "reject"],
        }
    return outcomes


def run(repetitions: int) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    episodes = build_batch()
    by_pair = {}
    for episode in episodes:
        by_pair.setdefault(episode["pair_id"], {})[episode["pair_condition"]] = episode
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "paired-task-batch-v1")
    client = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    if OUTPUT.exists():
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if previous.get("model") != "deepseek-flash":
            raise ValueError("existing probe result uses another model")
        rows = previous["rows"]
    else:
        rows = []
    completed = {(row["pair_id"], row["repetition"]) for row in rows if "conditions" in row}
    for pair_id in PAIRS:
        conflict, control = by_pair[pair_id]["conflict"], by_pair[pair_id]["control"]
        for repetition in range(1, repetitions + 1):
            if (pair_id, repetition) in completed:
                continue
            row = {"pair_id": pair_id, "repetition": repetition}
            try:
                first_conflict = _sample(client, conflict, 0)
                first_control = _sample(client, control, 0) if pair_id.startswith("C1") else first_conflict
                shared_local = _sample(client, conflict, 1)
                row["model_records"] = {
                    "first_conflict": first_conflict,
                    "first_control": first_control,
                    "shared_local": shared_local,
                }
                row["conditions"] = {
                    "conflict": _replay(conflict, [first_conflict, shared_local]),
                    "control": _replay(control, [first_control, shared_local]),
                }
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                row["error"] = str(exc)[:500]
            rows.append(row)
            OUTPUT.write_text(json.dumps({
                "status": "exploratory_single_review_synthetic_devices",
                "model": "deepseek-flash", "rows": rows,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            compact = {"pair_id": pair_id, "repetition": repetition,
                       "error": row.get("error_type")}
            if "conditions" in row:
                compact.update({
                    "conflict_independent_valid": row["conditions"]["conflict"]["IndependentMultiAgent"]["process_valid_success"],
                    "conflict_strong_valid": row["conditions"]["conflict"]["ConstraintCoordinator"]["process_valid_success"],
                    "control_independent_valid": row["conditions"]["control"]["IndependentMultiAgent"]["process_valid_success"],
                })
            print(json.dumps(compact, ensure_ascii=False), flush=True)
    return {"rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    run(args.repetitions)
