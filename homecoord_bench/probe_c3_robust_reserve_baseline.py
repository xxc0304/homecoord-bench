"""Strong rule baseline with exact feasibility across possible urgent arrivals."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import mean, median
from typing import Any

from probe_c3_future_pair import SOURCE
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_staggered_release import release_order_records
from probe_c3_structural_generalization import make_episode_from_specs
from probe_c3_uncertain_arrival_grid import (
    ARRIVALS_S, DEV_ARRIVALS_S, HELD_OUT_ARRIVALS_S, make_arrival_case,
)
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_robust_reserve_baseline_20260929.json"
POLICY = "RobustReserveCoordinator"


def potential_urgent_metadata(template_id: str) -> dict[str, Any]:
    """A disclosed possible task class, identical for present and absent cases."""
    urgent = min(TEMPLATES[template_id], key=lambda task: (task.deadline_min, task.task_id))
    return {
        "task_id": urgent.task_id,
        "power_kw": urgent.power_kw,
        "duration_ms": urgent.duration_min * 60_000,
        "deadline_ms": urgent.deadline_min * 60_000,
        "possible_release_ms": [seconds * 1000 for seconds in ARRIVALS_S],
        "interpretation": "known possible urgent class and time support; actual occurrence hidden",
    }


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    saved = json.loads(source.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for batch in saved["batches"]:
        template_id = batch["template_id"]
        records = batch["sample"]["records"]
        specs = TEMPLATES[template_id]
        if set(records) != {task.task_id for task in specs}:
            raise ValueError(f"incomplete batch: {template_id}/{batch['repetition']}")
        prior = potential_urgent_metadata(template_id)
        for pressure in PRESSURES:
            base = make_episode_from_specs(template_id, specs, pressure)
            for arrival_s in (None, *ARRIVALS_S):
                episode = make_arrival_case(base, arrival_s)
                episode["simulation"]["potential_urgent"] = deepcopy(prior)
                ordered = release_order_records(episode, records)
                client = MemoryReplayClient(deepcopy(ordered))
                trace, result = run_event_simulation(
                    deepcopy(episode), client, POLICY,
                    "saved proposals; disclosed possible urgent class, hidden occurrence",
                    shared_safety_gate=True,
                )
                client.assert_consumed()
                rows.append({
                    "template_id": template_id,
                    "repetition": batch["repetition"],
                    "nominal_pressure": pressure,
                    "future_arrival_s": arrival_s,
                    "all_tasks_served": all(result["task_service"].values()),
                    "all_deadlines_met": result["all_deadlines_met"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "defer_count": sum(event["type"] == "coordination_decision"
                                       and event.get("reason") == "future_viability_reservation"
                                       for event in trace["events"]),
                    "start_order": [event["task_id"] for event in trace["events"]
                                    if event["type"] == "action_started"],
                })
    summary: dict[str, Any] = {}
    for pressure in PRESSURES:
        selected = [row for row in rows if row["nominal_pressure"] == pressure]
        absent = [row for row in selected if row["future_arrival_s"] is None]
        summary[f"{pressure:g}"] = {
            "no_event": {
                "runs": len(absent),
                "all_deadlines_met": sum(row["all_deadlines_met"] for row in absent),
                "median_first_action_ms": median(
                    row["first_action_start_latency_ms"] for row in absent
                ),
            }
        }
        for label, arrivals in (("development", DEV_ARRIVALS_S),
                                ("held_out_times", HELD_OUT_ARRIVALS_S)):
            subset = [row for row in selected if row["future_arrival_s"] in arrivals]
            summary[f"{pressure:g}"][label] = {
                "runs": len(subset),
                "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                "success_rate": mean(row["all_deadlines_met"] for row in subset),
                "median_first_action_ms": median(
                    row["first_action_start_latency_ms"] for row in subset
                ),
            }
    report = {
        "schema_version": "c3-robust-reserve-baseline-0.1",
        "status": "exploratory_strong_rule_with_declared_possible_future_not_frozen",
        "new_api_calls": 0,
        "possible_arrival_times_s": list(ARRIVALS_S),
        "same_prior_in_present_and_absent_pair": True,
        "rows": rows,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"replays={len(result['rows'])}; wrote={OUTPUT}")
