"""Preregistered DeepSeek proposals for prospective P1/P2 C3 candidates."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_parallel_model_pilot import sample_parallel
from probe_c3_prospective_candidates_20260930 import (
    OUTDIR, POLICIES, PRESSURES, SAMPLE_TEMPLATE_INDICES, load_locked,
    preflight, sha256,
)
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_prospective_model_20260930.json"
RUN_DIR = ROOT / "runs" / "c3-prospective-model-20260930"
REPETITIONS = 2


def _save(payload: dict[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replay_batch(template: str, repetition: int,
                 records: dict[str, dict[str, Any]],
                 episodes: dict[tuple[str, float], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    expected = {task["task_id"] for task in episodes[template, 1.2]["task_stream"]}
    if set(records) != expected:
        return rows
    for pressure in PRESSURES:
        episode = episodes[template, pressure]
        ordered = [records[task["task_id"]] for task in episode["task_stream"]]
        for policy in POLICIES:
            client = MemoryReplayClient(deepcopy(ordered))
            trace, result = run_event_simulation(
                deepcopy(episode), client, policy,
                "prospective anonymized recorded-proposal replay",
                shared_safety_gate=True,
            )
            client.assert_consumed()
            rows.append({
                "template": template, "repetition": repetition,
                "pressure": pressure, "policy": policy,
                "first_safe_action_ms": result["first_action_start_latency_ms"],
                "all_tasks_served": all(result["task_service"].values()),
                "all_deadlines_met": result["all_deadlines_met"],
                "task_service": result["task_service"],
                "task_deadline_met": result["task_deadline_met"],
                "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                "shared_gate_rejections": result["shared_safety_gate_rejection_count"],
                "start_order": [e["task_id"] for e in trace["events"]
                                if e["type"] == "action_started"],
            })
    return rows


def run() -> dict[str, Any]:
    manifest, episodes = load_locked()
    pre = preflight()
    manifest_hash = sha256(OUTDIR / "manifest.json")
    if pre["manifest_sha256"] != manifest_hash:
        raise ValueError("preflight and locked manifest disagree")
    templates = manifest["model_sample_templates"]
    if templates != [f"P{index}" for index in SAMPLE_TEMPLATE_INDICES]:
        raise ValueError("model subset changed since preregistration")
    if OUTPUT.exists():
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if payload["manifest_sha256"] != manifest_hash:
            raise ValueError("existing result uses another candidate batch")
    else:
        payload = {
            "schema_version": "c3-prospective-model-0.1",
            "status": "controlled_prospective_model_probe_not_external_holdout",
            "manifest_sha256": manifest_hash,
            "model": "deepseek-flash",
            "templates": templates,
            "repetitions_target": REPETITIONS,
            "model_requests_planned": len(templates) * REPETITIONS * 3,
            "batches": [], "replays": [],
        }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    client = DeepSeekResponsesClient(
        model="deepseek-flash", max_attempts=2,
        logger=EventLogger(RUN_DIR / "model_events.jsonl", "c3-prospective-model-20260930"),
    )
    for template in templates:
        for repetition in range(1, REPETITIONS + 1):
            existing = next((b for b in payload["batches"]
                             if b["template"] == template and b["repetition"] == repetition), None)
            if existing is not None:
                errors = existing["sample"].get("errors", {})
                transport_blocked = bool(errors) and not existing["sample"].get("records") and all(
                    item.get("error_type") == "URLError" and "10013" in item.get("error", "")
                    for item in errors.values()
                )
                if not transport_blocked:
                    continue  # Model or protocol failures remain reported; no selective resampling.
            sample_episode = deepcopy(episodes[template, 1.2])
            sample_episode["episode_id"] = f"HC-C3-PUBLIC-{template}"
            sample_episode["base_episode_id"] = sample_episode["episode_id"]
            sample = sample_parallel(client, sample_episode, repetition)
            if existing is None:
                payload["batches"].append({
                    "template": template, "repetition": repetition, "sample": sample,
                })
            else:
                existing.setdefault("prior_transport_blocked_samples", []).append(existing["sample"])
                existing["sample"] = sample
            _save(payload)
            print(json.dumps({"template": template, "repetition": repetition,
                              "completion_order": sample["completion_order"],
                              "errors": sample["errors"]}, ensure_ascii=False), flush=True)
    payload["replays"] = [
        row for batch in payload["batches"]
        for row in replay_batch(batch["template"], batch["repetition"],
                                batch["sample"]["records"], episodes)
    ]
    payload["summary"] = {}
    for template in templates:
        payload["summary"][template] = {}
        for pressure in PRESSURES:
            key = f"{pressure:g}"
            payload["summary"][template][key] = {}
            for policy in POLICIES:
                rows = [r for r in payload["replays"] if r["template"] == template
                        and r["pressure"] == pressure and r["policy"] == policy]
                payload["summary"][template][key][policy] = {
                    "complete_batches": len(rows),
                    "all_tasks_served": sum(r["all_tasks_served"] for r in rows),
                    "all_deadlines_met": sum(r["all_deadlines_met"] for r in rows),
                    "median_first_safe_action_ms": median(r["first_safe_action_ms"] for r in rows)
                    if rows else None,
                }
    _save(payload)
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "model_requests_planned": result["model_requests_planned"],
        "complete_batches": sum(not b["sample"]["errors"] for b in result["batches"]),
        "replay_rows": len(result["replays"]), "summary": result["summary"],
    }, ensure_ascii=False, indent=2))
