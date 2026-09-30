"""Pair a released-task scheduler with the exact-future-prior reference rule."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_robust_reserve_baseline import potential_urgent_metadata
from probe_c3_future_pair import SOURCE
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_staggered_release import release_order_records
from probe_c3_structural_generalization import make_episode_from_specs
from probe_c3_uncertain_arrival_grid import ARRIVALS_S, make_arrival_case
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_information_boundary_20260929.json"
POLICIES = (
    "ObservedTaskFeasibilityCoordinator",
    "RobustReserveCoordinator",
    "GateRetryRule",
)


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
            for arrival_s in (None, *ARRIVALS_S):
                episode = make_arrival_case(base, arrival_s)
                ordered = release_order_records(episode, records)
                for policy in POLICIES:
                    configured = deepcopy(episode)
                    if policy == "RobustReserveCoordinator":
                        configured["simulation"]["potential_urgent"] = potential_urgent_metadata(template_id)
                    else:
                        configured["simulation"].pop("potential_urgent", None)
                    configured["simulation"]["blind_future_task_arrivals"] = True
                    client = MemoryReplayClient(deepcopy(ordered))
                    trace, result = run_event_simulation(
                        configured, client, policy,
                        "saved proposals; information boundary comparison",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "template_id": template_id,
                        "repetition": batch["repetition"],
                        "nominal_pressure": pressure,
                        "future_arrival_s": arrival_s,
                        "policy": policy,
                        "all_tasks_served": all(result["task_service"].values()),
                        "all_deadlines_met": result["all_deadlines_met"],
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "defer_count": sum(
                            event["type"] == "coordination_decision" and event.get("decision") == "defer"
                            for event in trace["events"]
                        ),
                    })
    summary: dict[str, Any] = {}
    for template_id in TEMPLATES:
        summary[template_id] = {}
        for pressure in PRESSURES:
            summary[template_id][f"{pressure:g}"] = {}
            for label, arrival in (("absent", None), ("present", "any")):
                summary[template_id][f"{pressure:g}"][label] = {}
                for policy in POLICIES:
                    subset = [row for row in rows if row["template_id"] == template_id
                              and row["nominal_pressure"] == pressure
                              and row["policy"] == policy
                              and ((row["future_arrival_s"] is None) if arrival is None
                                   else (row["future_arrival_s"] is not None))]
                    summary[template_id][f"{pressure:g}"][label][policy] = {
                        "runs": len(subset),
                        "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                        "median_first_action_ms": median(
                            row["first_action_start_latency_ms"] for row in subset
                            if row["first_action_start_latency_ms"] is not None
                        ),
                    }
    report = {
        "schema_version": "c3-information-boundary-0.1",
        "status": "exploratory_saved_proposals_not_frozen",
        "new_api_calls": 0,
        "saved_model_batches": len(saved["batches"]),
        "future_metadata_given_only_to": "RobustReserveCoordinator",
        "agent_request_identifiers_and_goals_blinded_to_future_arrival": True,
        "same_saved_proposals_reused_across_conditions": True,
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
