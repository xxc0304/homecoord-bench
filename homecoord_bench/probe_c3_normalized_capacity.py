"""Replay saved three-agent proposals across normalized C3 pressure levels."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from evaluate import ROOT
from make_c3_normalized_capacity_batch import CONDITIONS, make_condition
from probe_c3_three_load import POLICIES
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


SOURCE = ROOT / "results" / "c3_three_load_model_pilot_20260928.json"
OUTPUT = ROOT / "results" / "c3_normalized_capacity_replay_20260928.json"


def _complete_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    expected = {task["task_id"] for task in make_condition(*CONDITIONS[0])["task_stream"]}
    return [row for row in payload["rows"] if set(row.get("model_records", {})) == expected]


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    records = _complete_records(payload)
    if not records:
        raise ValueError("no complete saved proposal groups")

    rows: list[dict[str, Any]] = []
    for record_group in records:
        for name, ratio in CONDITIONS:
            episode = make_condition(name, ratio)
            ordered = [record_group["model_records"][task["task_id"]]
                       for task in episode["task_stream"]]
            for policy in POLICIES:
                client = MemoryReplayClient(deepcopy(ordered))
                trace, result = run_event_simulation(
                    deepcopy(episode), client, policy,
                    "saved-proposal normalized-capacity replay",
                    shared_safety_gate=True,
                )
                client.assert_consumed()
                rows.append({
                    "repetition": record_group["repetition"],
                    "condition": name.lower().replace("-", "_"),
                    "load_to_capacity_ratio": episode["resource_pressure"]["load_to_capacity_ratio"],
                    "capacity_kw": episode["resource_pressure"]["capacity_kw"],
                    "policy": policy,
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "all_tasks_served": all(result["task_service"].values()),
                    "all_deadlines_met": result["all_deadlines_met"],
                    "task_deadline_met": result["task_deadline_met"],
                    "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                    "process_valid_success": result["process_valid_success"],
                    "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                    "start_order": [event["task_id"] for event in trace["events"]
                                    if event["type"] == "action_started"],
                    "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                })

    summary: dict[str, Any] = {}
    for name, ratio in CONDITIONS:
        condition = name.lower().replace("-", "_")
        summary[condition] = {
            "load_to_capacity_ratio": round(ratio, 6),
            "by_policy": {},
        }
        for policy in POLICIES:
            subset = [row for row in rows
                      if row["condition"] == condition and row["policy"] == policy]
            summary[condition]["by_policy"][policy] = {
                "runs": len(subset),
                "all_tasks_served": sum(row["all_tasks_served"] for row in subset),
                "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                "process_valid_success": sum(row["process_valid_success"] for row in subset),
                "median_first_action_start_latency_ms": median(
                    row["first_action_start_latency_ms"] for row in subset
                    if row["first_action_start_latency_ms"] is not None
                ),
                "total_shared_safety_gate_rejections": sum(
                    row["shared_safety_gate_rejection_count"] for row in subset
                ),
            }

    report = {
        "experiment": "c3_normalized_resource_pressure_saved_proposal_replay",
        "status": "controlled_synthetic_capacity_mechanism_experiment",
        "source_proposals": str(source.relative_to(ROOT.parent)),
        "saved_proposal_groups": len(records),
        "api_calls": 0,
        "paired_design": (
            "same three tasks, saved proposals, model latencies, device cycles, deadlines, "
            "shared safety gate, and policies; only managed capacity changes"
        ),
        "summary": summary,
        "rows": rows,
        "limitations": [
            "Capacity is a controlled managed-power budget, not a measured household service rating.",
            "Nominal powers, fixed cycles, and deadlines remain synthetic assumptions.",
            "Five repetitions are proposal-latency samples for one task template, not households.",
            "The replay measures logical asynchronous timing rather than live parallel API calls.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote: {OUTPUT}")
