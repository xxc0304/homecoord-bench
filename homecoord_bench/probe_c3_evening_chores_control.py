"""Exploratory low-urgency C3 composition with a capacity-only control arm.

Power ratings reuse individually sourced records, while durations, deadlines,
co-occurrence, and managed capacity are controlled assumptions. This is an
author-designed negative control, not an independent or frozen household.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from statistics import median
from typing import Any

from make_c3_review_candidates import _without_factor
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_structural_generalization import (
    TaskSpec, latencies_for_order, make_episode_from_specs,
)
from probe_c3_three_load import ScriptedProposalClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation
from runtime.scheduling_oracle import ideal_schedule


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_evening_chores_control_20260929.json"
PROVENANCE = ROOT / "data" / "c3_non_nested_parameter_provenance_v0.1.json"
TASK_IDS = ("wash_dishes", "wash_clothes", "charge_ev")
PRESSURES = (0.8, 1.0, 1.2)
POLICIES = (
    "IndependentMultiAgent", "ConstraintCoordinator", "GateRetryRule",
    "DeadlineAwareCoordinator", "ObservedTaskFeasibilityCoordinator",
)


def specs() -> tuple[TaskSpec, ...]:
    existing = {task.task_id: task for group in TEMPLATES.values() for task in group}
    return tuple(existing[task_id] for task_id in TASK_IDS)


def make_candidates() -> list[dict[str, Any]]:
    episodes = [make_episode_from_specs("EVENING_CHORES_CONTROL", specs(), pressure)
                for pressure in PRESSURES]
    for episode in episodes:
        episode["source_type"] = "controlled_composition_from_sourced_device_ratings"
        episode["review_status"] = "exploratory_author_candidate_not_frozen"
        episode["scenario_assumptions"].update({
            "task_cooccurrence": "author_assumed_not_observed",
            "power_semantics": "full-cycle reservation at sourced rated or connection power",
            "cycle_and_deadline_semantics": "reused E4 controlled assumptions from existing templates",
            "capacity_semantics": "controlled managed-load budget, not a measured home limit",
        })
    return episodes


def run(output: Path = OUTPUT) -> dict[str, Any]:
    episodes = make_candidates()
    errors = [f"{episode['episode_id']}: {error}"
              for episode in episodes for error in validate_event_episode(episode)]
    if any(_without_factor(episode) != _without_factor(episodes[0])
           for episode in episodes[1:]):
        errors.append("paired episodes differ beyond capacity and pressure metadata")
    schedules = {f"{pressure:g}": ideal_schedule(episode)
                 for pressure, episode in zip(PRESSURES, episodes)}
    if any(schedule is None for schedule in schedules.values()):
        errors.append("one or more conditions have no ideal feasible schedule")
    if errors:
        raise ValueError(errors)
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    source_records = {record["task_id"]: record for record in provenance["records"]
                      if record["task_id"] in TASK_IDS}
    if set(source_records) != set(TASK_IDS):
        raise ValueError("source record missing for a chosen task")
    for task in specs():
        source = source_records[task.task_id]
        if source["configured"]["power_kw"] != task.power_kw:
            raise ValueError(f"power source mismatch: {task.task_id}")
    rows: list[dict[str, Any]] = []
    for pressure, episode in zip(PRESSURES, episodes):
        for order in itertools.permutations(TASK_IDS):
            latencies = latencies_for_order(order)
            for policy in POLICIES:
                trace, result = run_event_simulation(
                    episode, ScriptedProposalClient(latencies), policy,
                    "controlled low-urgency composition", shared_safety_gate=True,
                )
                rows.append({
                    "nominal_pressure": pressure,
                    "return_order": list(order),
                    "policy": policy,
                    "all_tasks_served": all(result["task_service"].values()),
                    "all_deadlines_met": result["all_deadlines_met"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "start_order": [event["task_id"] for event in trace["events"]
                                    if event["type"] == "action_started"],
                })
    summary = {
        f"{pressure:g}": {
            policy: {
                "runs": len(selected := [row for row in rows
                                  if row["nominal_pressure"] == pressure and row["policy"] == policy]),
                "all_deadlines_met": sum(row["all_deadlines_met"] for row in selected),
                "all_tasks_served": sum(row["all_tasks_served"] for row in selected),
                "median_first_action_ms": median(row["first_action_start_latency_ms"]
                                                  for row in selected),
            }
            for policy in POLICIES
        }
        for pressure in PRESSURES
    }
    report = {
        "schema_version": "c3-evening-chores-control-0.1",
        "status": "exploratory_author_composition_not_independent_household_or_frozen_data",
        "new_api_calls": 0,
        "base_template_count": 1,
        "task_ids": list(TASK_IDS),
        "pressure_levels": list(PRESSURES),
        "pair_variable": "managed shared power budget only",
        "ideal_feasible_schedules": schedules,
        "source_records": source_records,
        "summary": summary,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"replays={len(report['rows'])}; wrote={OUTPUT}")
