"""Paired future-urgent present/absent replay with a fixed online hold rule."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_gate_retry_baseline import NEW_POLICY as RETRY_POLICY
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_staggered_release import ideal_schedule, release_order_records, set_release_pattern
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
OUTPUT = ROOT / "results" / "c3_future_urgent_pair_20260929.json"
HOLD_UNTIL_MS = 2 * 60_000
METHODS = (
    "ConstraintCoordinator",
    RETRY_POLICY,
    "DeadlineAwareCoordinator",
    "FixedHoldUnknown",
    "ConditionalHoldAnnounced",
)


def make_pair(base: dict[str, Any], future_urgent: bool) -> dict[str, Any]:
    """Keep nonurgent tasks and the managed budget identical across a pair."""
    episode = set_release_pattern(base, "urgent_late_1m")
    urgent = min(episode["task_stream"], key=lambda task: (
        task["completion_deadline_ms"], task["task_id"]
    ))
    if not future_urgent:
        task_id, agent_id = urgent["task_id"], urgent["agent_id"]
        target = urgent["required_action"]["target"]
        episode["task_stream"] = [task for task in episode["task_stream"]
                                  if task["task_id"] != task_id]
        episode["agents"] = [agent for agent in episode["agents"]
                             if agent["agent_id"] != agent_id]
        episode["action_grounding"] = [item for item in episode["action_grounding"]
                                       if item["task_id"] != task_id]
        episode["tool_catalog"] = [item for item in episode["tool_catalog"]
                                   if item["agent_id"] != agent_id]
        episode["goals"] = [goal for goal in episode["goals"]
                            if goal["path"] != f"devices.{target}"]
        episode["home"]["resources"]["task_power_bounds_kw"].pop(task_id)
        total = sum(task["action_template"]["power_kw"]
                    for task in episode["task_stream"])
        pressure = episode["resource_pressure"]
        pressure["paired_full_task_rho"] = pressure["load_to_capacity_ratio"]
        pressure["sum_nominal_requested_power_kw"] = total
        pressure["load_to_capacity_ratio"] = round(
            total / episode["home"]["resources"]["max_power_kw"], 6
        )
        pressure["source"] = "controlled_future_urgent_absence_pair"
    episode["episode_id"] += "-FUTURE-URGENT" if future_urgent else "-NO-FUTURE-URGENT"
    episode["source_type"] = "controlled_future_urgent_pair"
    episode["review_status"] = "exploratory_not_frozen"
    episode["scenario_assumptions"]["future_urgent_present"] = future_urgent
    return episode


def method_policy_and_hold(method: str, future_urgent: bool) -> tuple[str, int | None]:
    if method == "FixedHoldUnknown":
        return "FixedHoldCoordinator", HOLD_UNTIL_MS
    if method == "ConditionalHoldAnnounced":
        return "FixedHoldCoordinator", HOLD_UNTIL_MS if future_urgent else 0
    return method, None


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
            for future_urgent in (False, True):
                episode = make_pair(base, future_urgent)
                feasible = ideal_schedule(episode) is not None
                ordered = release_order_records(episode, records)
                for method in METHODS:
                    policy, hold_until = method_policy_and_hold(method, future_urgent)
                    configured = deepcopy(episode)
                    if hold_until is not None:
                        configured["simulation"]["hold_until_ms"] = hold_until
                    client = MemoryReplayClient(deepcopy(ordered))
                    _, result = run_event_simulation(
                        configured, client, policy,
                        "saved parallel proposals; future urgent present/absent pair",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "template_id": template_id,
                        "repetition": batch["repetition"],
                        "nominal_pressure": pressure,
                        "future_urgent": future_urgent,
                        "ideal_feasible": feasible,
                        "method": method,
                        "policy": policy,
                        "hold_until_ms": hold_until,
                        "all_tasks_served": all(result["task_service"].values()),
                        "all_deadlines_met": result["all_deadlines_met"],
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                    })
    summary: dict[str, Any] = {}
    for pressure in PRESSURES:
        summary[f"{pressure:g}"] = {}
        for future_urgent in (False, True):
            key = "present" if future_urgent else "absent"
            subset = [row for row in rows if row["nominal_pressure"] == pressure
                      and row["future_urgent"] == future_urgent]
            summary[f"{pressure:g}"][key] = {
                method: {
                    "runs": len([row for row in subset if row["method"] == method]),
                    "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset
                                             if row["method"] == method),
                    "median_first_action_start_latency_ms": median(
                        row["first_action_start_latency_ms"] for row in subset
                        if row["method"] == method
                    ),
                }
                for method in METHODS
            }
    report = {
        "schema_version": "c3-future-urgent-pair-0.1",
        "status": "exploratory_saved_proposals_counterfactual_not_frozen",
        "new_api_calls": 0,
        "same_nonurgent_tasks_and_budget_within_pair": True,
        "fixed_unknown_hold_until_ms": HOLD_UNTIL_MS,
        "announced_conditional_comparator_has_future_presence_information": True,
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
