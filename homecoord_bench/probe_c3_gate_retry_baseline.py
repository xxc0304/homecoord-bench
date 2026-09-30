"""Test a safety-gate retry rule against the saved parallel model proposals."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import POLICIES, PRESSURES
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
OUTPUT = ROOT / "results" / "c3_gate_retry_baseline_20260929.json"
NEW_POLICY = "GateRetryRule"


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    saved = json.loads(source.read_text(encoding="utf-8"))
    rows = [dict(row) for row in saved["replays"]]
    for batch in saved["batches"]:
        template_id = batch["template_id"]
        records = batch["sample"]["records"]
        specs = TEMPLATES[template_id]
        if set(records) != {task.task_id for task in specs}:
            raise ValueError(f"incomplete batch: {template_id}/{batch['repetition']}")
        for pressure in PRESSURES:
            episode = make_episode_from_specs(template_id, specs, pressure)
            ordered = [records[task["task_id"]] for task in episode["task_stream"]]
            client = MemoryReplayClient(deepcopy(ordered))
            trace, result = run_event_simulation(
                deepcopy(episode), client, NEW_POLICY,
                "saved parallel proposals; safety-gate retry baseline",
                shared_safety_gate=True,
            )
            client.assert_consumed()
            rows.append({
                "template_id": template_id,
                "repetition": batch["repetition"],
                "pressure": pressure,
                "policy": NEW_POLICY,
                "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                "all_tasks_served": all(result["task_service"].values()),
                "all_deadlines_met": result["all_deadlines_met"],
                "task_deadline_met": result["task_deadline_met"],
                "process_valid_success": result["process_valid_success"],
                "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                "retry_queued_count": result["retry_queued_count"],
                "retry_scheduled_count": result["retry_scheduled_count"],
                "start_order": [event["task_id"] for event in trace["events"]
                                if event["type"] == "action_started"],
            })
    summary: dict[str, Any] = {}
    for template_id in TEMPLATES:
        summary[template_id] = {}
        for pressure in PRESSURES:
            summary[template_id][f"{pressure:g}"] = {}
            for policy in (*POLICIES, NEW_POLICY):
                subset = [row for row in rows if row["template_id"] == template_id
                          and row["pressure"] == pressure and row["policy"] == policy]
                summary[template_id][f"{pressure:g}"][policy] = {
                    "runs": len(subset),
                    "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                    "all_tasks_served": sum(row["all_tasks_served"] for row in subset),
                    "median_first_action_start_latency_ms": median(
                        row["first_action_start_latency_ms"] for row in subset
                        if row["first_action_start_latency_ms"] is not None
                    ),
                }
    report = {
        "schema_version": "c3-gate-retry-baseline-0.1",
        "status": "exploratory_saved_proposals_not_frozen_benchmark",
        "same_saved_model_proposals": True,
        "new_api_calls": 0,
        "new_replays": sum(row["policy"] == NEW_POLICY for row in rows),
        "policies": [*POLICIES, NEW_POLICY],
        "rows": rows,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"new_replays={report['new_replays']}; wrote={OUTPUT}")
