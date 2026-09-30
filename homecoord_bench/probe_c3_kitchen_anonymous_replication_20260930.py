"""Anonymized DeepSeek replication on the previously explored kitchen C3 structure."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_non_nested_templates import POLICIES
from probe_c3_parallel_model_pilot import sample_parallel
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "revision_drafts" / "20260929_c3_non_nested_review"
SAMPLE_PATH = ROOT / "revision_drafts" / "20260930_kitchen_blind_replication" / "HC-C3-KITCHEN-ANON-SAMPLE-V01.json"
OUTPUT = ROOT / "results" / "c3_kitchen_anonymous_replication_20260930.json"
RUN_DIR = ROOT / "runs" / "c3-kitchen-anonymous-replication-20260930"
REPETITIONS = 3
PRESSURES = ("0.8", "1.2", "1.6")
SAMPLE_SHA256 = "9706564C73EC97DD55340D5117D6E6F408BA030229CCA197054220FC03DDD4C4"
SOURCE_SHA256 = {
    "HC-C3-KITCHEN_CIRCUIT-RHO-0.8.json": "D287A668C63097E1F07B9AF6EB6BAA013F5CD4410C93631F7A28C76C2AD34285",
    "HC-C3-KITCHEN_CIRCUIT-RHO-1.2.json": "E3DB065C595AAD4D4884A2959B4E58C0A5B18AADC0FAE24EE326FFAF59D99508",
    "HC-C3-KITCHEN_CIRCUIT-RHO-1.6.json": "4F408B1007034F2145B791705D39F348FC029DFF7E2EC26A7A59E0155986D70B",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _check_inputs() -> None:
    if _digest(SAMPLE_PATH) != SAMPLE_SHA256:
        raise ValueError("anonymous model-sampling input changed after preregistration")
    for name, expected in SOURCE_SHA256.items():
        if _digest(SOURCE_DIR / name) != expected:
            raise ValueError(f"pressure replay input changed after preregistration: {name}")
    sample = _load(SAMPLE_PATH)
    if sample["episode_id"] != "HC-C3-PUB-M8V4":
        raise ValueError("public sampling episode ID is not the preregistered opaque ID")
    for task in sample["task_stream"]:
        agent = next(item for item in sample["agents"] if item["agent_id"] == task["agent_id"])
        request = build_agent_request(
            sample, agent, task, architecture="IndependentMultiAgent",
            current_time_ms=task["release_at_ms"],
            current_state=sample["initial_state"]["values"],
            state_version=sample["initial_state"]["version"],
            request_id=f"HC-C3-PUB-M8V4:preflight:{task['task_id']}",
        )
        text = json.dumps(request, ensure_ascii=False)
        if any(label in text for label in ("RHO", "rho=", "1.2", "6.0")):
            raise ValueError(f"condition label leaked into {task['task_id']} request")
        if "required_action" in request["task"] or "action_template" in request["task"]:
            raise ValueError(f"scoring template leaked into {task['task_id']} request")
        other_ids = {item["task_id"] for item in sample["task_stream"]} - {task["task_id"]}
        if any(task_id in text for task_id in other_ids):
            raise ValueError(f"another task is visible in {task['task_id']} request")


def _summary_row(pressure: str, policy: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": len(rows),
        "all_tasks_served": sum(bool(row["all_tasks_served"]) for row in rows),
        "all_deadlines_met": sum(bool(row["all_deadlines_met"]) for row in rows),
        "median_first_safe_action_ms": median(row["first_safe_action_ms"] for row in rows),
        "median_all_tasks_finished_ms": median(
            row["all_tasks_finished_ms"] for row in rows
            if row["all_tasks_finished_ms"] is not None
        ) if any(row["all_tasks_finished_ms"] is not None for row in rows) else None,
    }


def _replay_batches(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in payload["batches"]:
        sample = batch["sample"]
        if sample.get("errors"):
            continue
        records = sample["records"]
        for pressure in PRESSURES:
            source_name = f"HC-C3-KITCHEN_CIRCUIT-RHO-{pressure}.json"
            episode = _load(SOURCE_DIR / source_name)
            ordered = [records[task["task_id"]] for task in episode["task_stream"]]
            for policy in POLICIES:
                client = MemoryReplayClient(deepcopy(ordered))
                trace, result = run_event_simulation(
                    deepcopy(episode), client, policy,
                    "anonymized cross-structure proposal replay",
                    shared_safety_gate=True,
                )
                client.assert_consumed()
                rows.append({
                    "repetition": batch["repetition"],
                    "pressure": pressure,
                    "policy": policy,
                    "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                    "first_safe_action_ms": result["first_action_start_latency_ms"],
                    "task_service": result["task_service"],
                    "task_finish_ms": result["task_action_finish_time_ms"],
                    "task_deadline_met": result["task_deadline_met"],
                    "all_tasks_served": all(result["task_service"].values()),
                    "all_deadlines_met": result["all_deadlines_met"],
                    "all_tasks_finished_ms": max(result["task_action_finish_time_ms"].values())
                    if all(value is not None for value in result["task_action_finish_time_ms"].values())
                    else None,
                    "shared_gate_rejections": result["shared_safety_gate_rejection_count"],
                    "constraint_violation_duration_ms": result["state_constraint_violation_duration_ms"],
                    "start_order": [event["task_id"] for event in trace["events"]
                                    if event["type"] == "action_started"],
                })
    return rows


def run() -> dict[str, Any]:
    _check_inputs()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        payload = _load(OUTPUT)
        if payload.get("sample_sha256") != SAMPLE_SHA256 or payload.get("source_sha256") != SOURCE_SHA256:
            raise ValueError("existing output belongs to different preregistered inputs")
    else:
        payload = {
            "schema_version": "c3-kitchen-anonymous-replication-0.1",
            "status": "exploratory_cross_structure_replication_not_holdout",
            "model": "deepseek-flash",
            "repetitions_target": REPETITIONS,
            "sample_sha256": SAMPLE_SHA256,
            "source_sha256": SOURCE_SHA256,
            "sampled_pressure": "1.2; pressure label and capacity are excluded from model requests",
            "agent_request_count": 0,
            "batches": [],
            "replays": [],
        }
    client = DeepSeekResponsesClient(
        model="deepseek-flash", max_attempts=2,
        logger=EventLogger(RUN_DIR / "model_events.jsonl", "c3-kitchen-anonymous-replication-20260930"),
    )
    sample_episode = _load(SAMPLE_PATH)
    for repetition in range(1, REPETITIONS + 1):
        existing = next((item for item in payload["batches"] if item["repetition"] == repetition), None)
        if existing and not existing["sample"].get("errors"):
            continue
        sample = sample_parallel(client, sample_episode, repetition)
        payload["agent_request_count"] += 3
        if existing:
            existing.setdefault("prior_failed_samples", []).append(existing["sample"])
            existing["sample"] = sample
        else:
            payload["batches"].append({"repetition": repetition, "sample": sample})
        payload["replays"] = _replay_batches(payload)
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"repetition": repetition, "completion_order": sample["completion_order"],
                          "errors": sample["errors"]}, ensure_ascii=False), flush=True)
    payload["replays"] = _replay_batches(payload)
    summary: dict[str, Any] = {}
    for pressure in PRESSURES:
        summary[pressure] = {}
        for policy in POLICIES:
            selected = [row for row in payload["replays"]
                        if row["pressure"] == pressure and row["policy"] == policy]
            if selected:
                summary[pressure][policy] = _summary_row(pressure, policy, selected)
    payload["summary"] = summary
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "complete_batches": sum(not batch["sample"].get("errors") for batch in result["batches"]),
        "agent_requests_issued": result["agent_request_count"],
        "offline_replays": len(result["replays"]),
        "summary": result.get("summary", {}),
        "output": str(OUTPUT),
    }, ensure_ascii=False, indent=2))
