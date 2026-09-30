"""Small real-parallel DeepSeek proposal pilot on the C3 laundry v0.2 task."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_c3_parallel_model_pilot import sample_parallel
from probe_next_core_candidates_20260930 import (
    LOCKED_SHA256_V02,
    POLICIES,
    SOURCE_V02,
    _one,
)
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_laundry_real_model_pilot_20260930.json"
EVENTS = ROOT / "runs" / "c3-laundry-real-model-20260930" / "model_events.jsonl"
PRESSURES = ("0.8", "1.2", "1.6")
REPETITIONS = 3


def _episode(pressure: str) -> dict[str, Any]:
    name = f"HC-C3-LAUNDRY_HEAT_V02-RHO-{pressure}.json"
    path = SOURCE_V02 / name
    if hashlib.sha256(path.read_bytes()).hexdigest().upper() != LOCKED_SHA256_V02[name]:
        raise ValueError(f"v0.2 candidate changed after preregistration: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(payload: dict[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def run() -> dict[str, Any]:
    base = _episode("1.2")
    if OUTPUT.exists():
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if payload.get("preregistered_input_sha256") != LOCKED_SHA256_V02:
            raise ValueError("existing output refers to a different task version")
    else:
        payload = {
            "schema_version": "c3-laundry-real-model-pilot-0.1",
            "status": "post_feasibility_repair_exploratory_not_frozen_benchmark",
            "model": "deepseek-flash",
            "preregistered_input_sha256": LOCKED_SHA256_V02,
            "batches": [],
            "replays": [],
        }
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    model = DeepSeekResponsesClient(
        model="deepseek-flash",
        logger=EventLogger(EVENTS, "c3-laundry-real-model-20260930"),
    )
    for repetition in range(1, REPETITIONS + 1):
        existing = next((batch for batch in payload["batches"]
                         if batch["repetition"] == repetition), None)
        if existing is None or existing["sample"]["errors"]:
            sample = sample_parallel(model, base, repetition)
            if existing is None:
                existing = {"repetition": repetition, "sample": sample}
                payload["batches"].append(existing)
            else:
                existing.setdefault("prior_failed_samples", []).append(existing["sample"])
                existing["sample"] = sample
            _write(payload)
            print(json.dumps({"repetition": repetition,
                              "completion_order": sample["completion_order"],
                              "errors": sample["errors"]}, ensure_ascii=False), flush=True)
        if existing["sample"]["errors"]:
            continue
    rows = []
    for batch in payload["batches"]:
        if batch["sample"]["errors"]:
            continue
        records = batch["sample"]["records"]
        for pressure in PRESSURES:
            episode = _episode(pressure)
            if set(records) != {task["task_id"] for task in episode["task_stream"]}:
                raise ValueError("incomplete model batch")
            ordered = [records[task["task_id"]] for task in episode["task_stream"]]
            for policy in (*POLICIES, "CapacityAwareDeadlineCoordinator"):
                client = MemoryReplayClient(deepcopy(ordered))
                row = _one(episode, f"rho={pressure}",
                           f"parallel-model-{batch['repetition']}", policy, client)
                client.assert_consumed()
                rows.append(row)
    payload["replays"] = rows
    _write(payload)
    return payload


if __name__ == "__main__":
    report = run()
    print(json.dumps({"complete_batches": sum(not x["sample"]["errors"]
                                          for x in report["batches"]),
                      "replays": len(report["replays"]),
                      "output": str(OUTPUT)}, ensure_ascii=False))
