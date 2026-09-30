"""Small live DeepSeek check after hiding unreleased goals and scenario IDs.

The initially released tasks in each template are sampled concurrently. The urgent
task is sampled separately at its release. Saved decisions are then replayed
across paired arrival conditions and policies; no API call occurs in replay.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from probe_c3_future_pair import make_pair
from probe_c3_information_boundary import POLICIES
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_robust_reserve_baseline import potential_urgent_metadata
from probe_c3_staggered_release import release_order_records
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_blinded_live_pilot_20260929.json"
RUN_DIR = ROOT / "runs" / "c3-blinded-live-pilot-20260929"
URGENT_ARRIVAL_S = 60


def _request(episode: dict[str, Any], task: dict[str, Any],
             released_task_ids: set[str]) -> dict[str, Any]:
    agent = next(item for item in episode["agents"] if item["agent_id"] == task["agent_id"])
    request = build_agent_request(
        episode, agent, task, architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
        request_id=f"{episode['base_episode_id']}:blind-live:{task['task_id']}",
        released_task_ids=released_task_ids,
    )
    if "required_action" in request["task"] or "action_template" in request["task"]:
        raise AssertionError("evaluation answer leaked into model request")
    return request


def _paired_requests(template_id: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    specs = TEMPLATES[template_id]
    base = make_episode_from_specs(template_id, specs, 1.2)
    present, absent = make_pair(base, True), make_pair(base, False)
    for episode in (present, absent):
        episode["simulation"]["blind_future_task_arrivals"] = True
    urgent_id = min(present["task_stream"], key=lambda task: (
        task["completion_deadline_ms"], task["task_id"]
    ))["task_id"]
    initially_released = {task["task_id"] for task in present["task_stream"]
                          if task["task_id"] != urgent_id}
    requests: dict[str, dict[str, Any]] = {}
    for task in present["task_stream"]:
        visible = initially_released if task["task_id"] != urgent_id else set(initially_released) | {urgent_id}
        requests[task["task_id"]] = _request(present, task, visible)
        if task["task_id"] != urgent_id:
            absent_task = next(item for item in absent["task_stream"]
                               if item["task_id"] == task["task_id"])
            if requests[task["task_id"]] != _request(absent, absent_task, visible):
                raise AssertionError("future-present and future-absent requests differ before release")
    return requests, {"urgent_id": urgent_id, "initially_released": sorted(initially_released)}


def _recover_completed(template_id: str, requests: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Reuse completed calls from an interrupted batch; never replay a failed call."""
    path = RUN_DIR / "model_events.jsonl"
    if not path.exists():
        return {}
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    prefix = f"HC-C3-{template_id}:blind-live:"
    starts = [float(event["elapsed_ms"]) for event in events
              if event.get("event_type") == "model_call_started"
              and event.get("request_id", "").startswith(prefix)]
    batch_start = min(starts) if starts else 0.0
    recovered: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "model_call_completed":
            continue
        request_id = event.get("request_id", "")
        if not request_id.startswith(prefix):
            continue
        task_id = request_id.removeprefix(prefix)
        if task_id in requests:
            duration = max(1, round(float(event["latency_ms"])))
            recovered[task_id] = {
                "request": requests[task_id],
                "decision": event["decision"],
                "call_duration_ms": duration,
                "logical_latency_ms": max(1, round(float(event["elapsed_ms"]) - batch_start)),
                "timing_provenance": "recovered_original_batch",
            }
    return recovered


def _sample(client: DeepSeekResponsesClient, requests: dict[str, dict[str, Any]],
            urgent_id: str, existing: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    batch_started = perf_counter_ns()

    def call(task_id: str) -> tuple[str, dict[str, Any]]:
        started = perf_counter_ns()
        decision = client.decide(requests[task_id], PILOT_INSTRUCTIONS)
        finished = perf_counter_ns()
        return task_id, {
            "request": requests[task_id],
            "decision": decision,
            "call_duration_ms": max(1, round((finished - started) / 1_000_000)),
            "logical_latency_ms": max(1, round((finished - batch_started) / 1_000_000)),
        }

    records: dict[str, dict[str, Any]] = dict(existing or {})
    initial = [task_id for task_id in requests if task_id != urgent_id and task_id not in records]
    if initial:
        with ThreadPoolExecutor(max_workers=len(initial)) as pool:
            futures = {pool.submit(call, task_id): task_id for task_id in initial}
            for future in as_completed(futures):
                task_id, record = future.result()
                record["timing_provenance"] = (
                    "individual_retry_duration_proxy" if existing else "original_parallel_batch"
                )
                records[task_id] = record
    # The urgent proposal becomes available only after its virtual release.
    if urgent_id not in records:
        urgent_start = perf_counter_ns()
        decision = client.decide(requests[urgent_id], PILOT_INSTRUCTIONS)
        records[urgent_id] = {
            "request": requests[urgent_id],
            "decision": decision,
            "call_duration_ms": max(1, round((perf_counter_ns() - urgent_start) / 1_000_000)),
            "logical_latency_ms": max(1, round((perf_counter_ns() - urgent_start) / 1_000_000)),
            "timing_provenance": "separate_urgent_release_call",
        }
    return records


def _replay(template_id: str, records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = TEMPLATES[template_id]
    for pressure in PRESSURES:
        base = make_episode_from_specs(template_id, specs, pressure)
        for present in (False, True):
            episode = make_pair(base, present)
            episode["simulation"]["blind_future_task_arrivals"] = True
            ordered = release_order_records(episode, records)
            for policy in POLICIES:
                configured = deepcopy(episode)
                if policy == "RobustReserveCoordinator":
                    configured["simulation"]["potential_urgent"] = potential_urgent_metadata(template_id)
                client = MemoryReplayClient(deepcopy(ordered))
                trace, result = run_event_simulation(
                    configured, client, policy, "blinded live proposal replay",
                    shared_safety_gate=True,
                )
                client.assert_consumed()
                rows.append({
                    "template_id": template_id,
                    "nominal_pressure": pressure,
                    "urgent_present": present,
                    "policy": policy,
                    "all_deadlines_met": result["all_deadlines_met"],
                    "all_tasks_served": all(result["task_service"].values()),
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "start_order": [event["task_id"] for event in trace["events"]
                                    if event["type"] == "action_started"],
                })
    return rows


def run(output: Path = OUTPUT) -> dict[str, Any]:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "c3-blinded-live-pilot-20260929")
    model = DeepSeekResponsesClient(model="deepseek-flash", max_attempts=2, logger=logger)
    payload: dict[str, Any] = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {
        "schema_version": "c3-blinded-live-pilot-0.1",
        "status": "exploratory_one_batch_per_template_not_frozen",
        "model": "deepseek-flash",
        "intended_successful_proposals": sum(len(specs) for specs in TEMPLATES.values()),
        "urgent_arrival_s": URGENT_ARRIVAL_S,
        "batches": [],
        "replays": [],
    }
    payload.pop("intended_api_calls", None)
    payload["intended_successful_proposals"] = sum(len(specs) for specs in TEMPLATES.values())
    for template_id in TEMPLATES:
        if any(batch["template_id"] == template_id for batch in payload["batches"]):
            continue
        requests, metadata = _paired_requests(template_id)
        recovered = _recover_completed(template_id, requests)
        records = _sample(model, requests, metadata["urgent_id"], recovered)
        payload["batches"].append({
            "template_id": template_id, **metadata, "records": records,
        })
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["replays"].extend(_replay(template_id, records))
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{template_id}: saved {len(records)} live proposals and {len(payload['replays'])} cumulative replays", flush=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = run()
    print(f"saved_proposals={sum(len(batch['records']) for batch in report['batches'])}; replays={len(report['replays'])}; wrote={OUTPUT}")
