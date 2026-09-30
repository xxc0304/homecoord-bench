"""Controlled asynchronous task-release replay using saved model decisions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_c3_gate_retry_baseline import NEW_POLICY
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import POLICIES, PRESSURES
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient
from runtime.scheduling_oracle import ideal_schedule


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
OUTPUT = ROOT / "results" / "c3_staggered_release_20260929.json"
SCENARIOS = ("co_release", "urgent_late_1m", "urgent_late_3m", "urgent_first_1m")
ALL_POLICIES = (*POLICIES, NEW_POLICY)
MINUTE = 60_000


def set_release_pattern(episode: dict[str, Any], scenario: str) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(scenario)
    changed = deepcopy(episode)
    urgent = min(changed["task_stream"], key=lambda task: (
        task["completion_deadline_ms"], task["task_id"]
    ))["task_id"]
    for task in changed["task_stream"]:
        if scenario == "urgent_late_1m" and task["task_id"] == urgent:
            task["release_at_ms"] = MINUTE
        elif scenario == "urgent_late_3m" and task["task_id"] == urgent:
            task["release_at_ms"] = 3 * MINUTE
        elif scenario == "urgent_first_1m" and task["task_id"] != urgent:
            task["release_at_ms"] = MINUTE
    changed["episode_id"] += f"-{scenario.upper()}"
    changed["source_type"] = "controlled_staggered_release_probe"
    changed["review_status"] = "exploratory_not_frozen"
    changed["scenario_assumptions"]["release_semantics"] = (
        "researcher-controlled release offsets; original absolute deadlines retained"
    )
    return changed


def release_order_records(episode: dict[str, Any],
                          records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """MemoryReplayClient is positional, so align records to release-queue order."""
    tasks = sorted(enumerate(episode["task_stream"]),
                   key=lambda item: (item[1]["release_at_ms"], item[0]))
    return [records[task["task_id"]] for _, task in tasks]


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    saved = json.loads(source.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for batch in saved["batches"]:
        template_id = batch["template_id"]
        records = batch["sample"]["records"]
        specs = TEMPLATES[template_id]
        if set(records) != {task.task_id for task in specs}:
            raise ValueError(f"incomplete batch: {template_id}/{batch['repetition']}")
        for pressure in PRESSURES:
            base = make_episode_from_specs(template_id, specs, pressure)
            for scenario in SCENARIOS:
                episode = set_release_pattern(base, scenario)
                feasible = ideal_schedule(episode) is not None
                ordered = release_order_records(episode, records)
                for policy in ALL_POLICIES:
                    client = MemoryReplayClient(deepcopy(ordered))
                    trace, result = run_event_simulation(
                        deepcopy(episode), client, policy,
                        "saved parallel proposals; controlled task release",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "template_id": template_id,
                        "repetition": batch["repetition"],
                        "pressure": pressure,
                        "scenario": scenario,
                        "ideal_feasible": feasible,
                        "policy": policy,
                        "proposal_count": result["proposal_count"],
                        "all_tasks_served": all(result["task_service"].values()),
                        "all_deadlines_met": result["all_deadlines_met"],
                        "task_deadline_met": result["task_deadline_met"],
                        "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                        "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "retry_queued_count": result["retry_queued_count"],
                        "start_order": [event["task_id"] for event in trace["events"]
                                        if event["type"] == "action_started"],
                    })
    summary: dict[str, Any] = {}
    for scenario in SCENARIOS:
        summary[scenario] = {}
        for pressure in PRESSURES:
            selected = [row for row in rows if row["scenario"] == scenario
                        and row["pressure"] == pressure]
            summary[scenario][f"{pressure:g}"] = {
                "ideal_feasible_templates": sorted({row["template_id"] for row in selected
                                                     if row["ideal_feasible"]}),
                "by_policy": {
                    policy: {
                        "all_deadlines_met": sum(row["all_deadlines_met"] for row in selected
                                                 if row["policy"] == policy),
                        "runs": sum(row["policy"] == policy for row in selected),
                    }
                    for policy in ALL_POLICIES
                },
            }
    report = {
        "schema_version": "c3-staggered-release-0.1",
        "status": "exploratory_saved_proposals_release_counterfactual",
        "same_saved_model_proposals": True,
        "new_api_calls": 0,
        "scenarios": list(SCENARIOS),
        "rows": rows,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"replays={len(report['rows'])}; wrote={OUTPUT}")
