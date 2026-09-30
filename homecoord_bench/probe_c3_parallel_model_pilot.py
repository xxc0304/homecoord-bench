"""Live parallel DeepSeek proposal pilot for two non-nested C3 templates.

Unlike earlier sequential collection, all specialist calls in one template
start together.  Each recorded logical latency is the completion offset from a
shared batch start, so replay represents observed parallel return order.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from evaluate import ROOT
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from probe_c3_non_nested_templates import POLICIES, TEMPLATES
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient


OUTPUT = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
RUN_DIR = ROOT / "runs" / "c3-parallel-model-pilot-20260929"
PRESSURES = (0.8, 1.2, 1.6)


def _request(episode: dict[str, Any], task: dict[str, Any], repetition: int) -> dict[str, Any]:
    agent = next(item for item in episode["agents"] if item["agent_id"] == task["agent_id"])
    request = build_agent_request(
        episode,
        agent,
        task,
        architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
        request_id=f"{episode['base_episode_id']}:{repetition}:{task['task_id']}",
    )
    if "required_action" in request["task"] or "action_template" in request["task"]:
        raise AssertionError("hidden answer leaked into model request")
    return request


def sample_parallel(client: Any, episode: dict[str, Any], repetition: int) -> dict[str, Any]:
    """Issue all specialist calls concurrently and retain task-keyed records."""
    requests = {
        task["task_id"]: _request(episode, task, repetition)
        for task in episode["task_stream"]
    }
    batch_started = perf_counter_ns()

    def call_one(task_id: str) -> tuple[str, dict[str, Any]]:
        call_started = perf_counter_ns()
        decision = client.decide(requests[task_id], PILOT_INSTRUCTIONS)
        finished = perf_counter_ns()
        return task_id, {
            "request": requests[task_id],
            "decision": decision,
            "call_duration_ms": max(1, round((finished - call_started) / 1_000_000)),
            "logical_latency_ms": max(1, round((finished - batch_started) / 1_000_000)),
        }

    records: dict[str, dict[str, Any]] = {}
    errors: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        futures = {pool.submit(call_one, task_id): task_id for task_id in requests}
        for future in as_completed(futures):
            task_id = futures[future]
            try:
                completed_id, record = future.result()
                records[completed_id] = record
            except Exception as exc:  # Preserve partial records for audit/resume.
                errors[task_id] = {
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
    return {
        "records": records,
        "errors": errors,
        "parallel_batch_wall_ms": max(1, round((perf_counter_ns() - batch_started) / 1_000_000)),
        "completion_order": [
            task_id for task_id, _ in sorted(
                records.items(), key=lambda item: item[1]["logical_latency_ms"]
            )
        ],
    }


def replay(template_id: str, records: dict[str, dict[str, Any]],
           repetition: int) -> list[dict[str, Any]]:
    specs = TEMPLATES[template_id]
    expected = {task.task_id for task in specs}
    if set(records) != expected:
        return []
    rows: list[dict[str, Any]] = []
    for pressure in PRESSURES:
        episode = make_episode_from_specs(template_id, specs, pressure)
        ordered = [records[task["task_id"]] for task in episode["task_stream"]]
        for policy in POLICIES:
            client = MemoryReplayClient(deepcopy(ordered))
            trace, result = run_event_simulation(
                deepcopy(episode), client, policy, "parallel recorded-proposal replay",
                shared_safety_gate=True,
            )
            client.assert_consumed()
            rows.append({
                "template_id": template_id,
                "repetition": repetition,
                "pressure": pressure,
                "policy": policy,
                "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                "all_tasks_served": all(result["task_service"].values()),
                "all_deadlines_met": result["all_deadlines_met"],
                "task_deadline_met": result["task_deadline_met"],
                "process_valid_success": result["process_valid_success"],
                "start_order": [
                    event["task_id"] for event in trace["events"]
                    if event["type"] == "action_started"
                ],
            })
    return rows


def design() -> dict[str, Any]:
    return {
        "model": "deepseek-flash",
        "templates": list(TEMPLATES),
        "calls_per_repetition": sum(len(tasks) for tasks in TEMPLATES.values()),
        "true_parallel_within_template": True,
        "templates_sampled_sequentially": True,
        "pressures_replayed": list(PRESSURES),
        "policies": list(POLICIES),
        "same_proposals_and_observed_parallel_latencies_across_policies": True,
    }


def run(repetitions: int = 1, output: Path = OUTPUT) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        payload = json.loads(output.read_text(encoding="utf-8"))
        if payload["design"] != design():
            raise ValueError("existing output uses a different design")
    else:
        payload = {
            "status": "live_parallel_model_proposal_pilot_controlled_device_assumptions",
            "design": design(),
            "batches": [],
            "replays": [],
        }
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "c3-parallel-model-pilot")
    model = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    for repetition in range(1, repetitions + 1):
        for template_id, specs in TEMPLATES.items():
            existing = next((
                batch for batch in payload["batches"]
                if batch["repetition"] == repetition and batch["template_id"] == template_id
            ), None)
            if existing and set(existing["sample"].get("records", {})) == {
                task.task_id for task in specs
            }:
                continue
            episode = make_episode_from_specs(template_id, specs, 1.2)
            sample = sample_parallel(model, episode, repetition)
            batch = {"template_id": template_id, "repetition": repetition, "sample": sample}
            payload["batches"] = [
                item for item in payload["batches"]
                if not (item["repetition"] == repetition and item["template_id"] == template_id)
            ] + [batch]
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({
                "template_id": template_id,
                "repetition": repetition,
                "completion_order": sample["completion_order"],
                "errors": sample["errors"],
            }, ensure_ascii=False), flush=True)
        payload["replays"] = [
            row
            for batch in payload["batches"]
            for row in replay(batch["template_id"], batch["sample"].get("records", {}),
                              batch["repetition"])
        ]
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    report = run(args.repetitions)
    print(json.dumps({
        "complete_batches": sum(not batch["sample"]["errors"] for batch in report["batches"]),
        "replays": len(report["replays"]),
        "output": str(OUTPUT),
    }, ensure_ascii=False))
