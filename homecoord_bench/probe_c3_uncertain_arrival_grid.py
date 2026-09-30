"""Sweep varied future-arrival times against non-aligned fixed hold windows."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import mean, median
from typing import Any

from probe_c3_future_pair import SOURCE, make_pair
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_staggered_release import ideal_schedule, release_order_records
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_uncertain_arrival_grid_20260929.json"
ARRIVALS_S = (15, 30, 45, 60, 90, 120)
HOLD_WINDOWS_S = (0, 20, 40, 70, 100, 130)
DEV_ARRIVALS_S = (15, 60, 120)
HELD_OUT_ARRIVALS_S = (30, 45, 90)
HYPOTHETICAL_EVENT_PROBABILITIES = (0.25, 0.5, 0.75)


def make_arrival_case(base: dict[str, Any], arrival_s: int | None) -> dict[str, Any]:
    episode = make_pair(base, arrival_s is not None)
    if arrival_s is not None:
        if arrival_s not in ARRIVALS_S:
            raise ValueError(arrival_s)
        urgent = min(episode["task_stream"], key=lambda task: (
            task["completion_deadline_ms"], task["task_id"]
        ))
        urgent["release_at_ms"] = arrival_s * 1000
    episode["episode_id"] += f"-ARRIVAL-{arrival_s if arrival_s is not None else 'NONE'}"
    episode["scenario_assumptions"]["future_arrival_s"] = arrival_s
    return episode


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
                ideal_feasible = ideal_schedule(episode) is not None
                ordered = release_order_records(episode, records)
                for hold_s in HOLD_WINDOWS_S:
                    configured = deepcopy(episode)
                    configured["simulation"]["hold_until_ms"] = hold_s * 1000
                    client = MemoryReplayClient(deepcopy(ordered))
                    _, result = run_event_simulation(
                        configured, client, "FixedHoldCoordinator",
                        "saved parallel proposals; varied future-arrival grid",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "template_id": template_id,
                        "repetition": batch["repetition"],
                        "nominal_pressure": pressure,
                        "future_arrival_s": arrival_s,
                        "hold_s": hold_s,
                        "ideal_feasible": ideal_feasible,
                        "all_deadlines_met": result["all_deadlines_met"],
                        "all_tasks_served": all(result["task_service"].values()),
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    })
    summary: dict[str, Any] = {}
    for pressure in PRESSURES:
        pressure_rows = [row for row in rows if row["nominal_pressure"] == pressure]
        summary[f"{pressure:g}"] = {}
        for hold_s in HOLD_WINDOWS_S:
            selected = [row for row in pressure_rows if row["hold_s"] == hold_s]
            absent = [row for row in selected if row["future_arrival_s"] is None]
            summary[f"{pressure:g}"][str(hold_s)] = {
                "no_event": {
                    "runs": len(absent),
                    "all_deadlines_met": sum(row["all_deadlines_met"] for row in absent),
                    "median_first_action_ms": median(
                        row["first_action_start_latency_ms"] for row in absent
                    ),
                },
                "by_arrival": {
                    str(arrival_s): {
                        "runs": len(subset := [row for row in selected
                                               if row["future_arrival_s"] == arrival_s]),
                        "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                    }
                    for arrival_s in ARRIVALS_S
                },
            }
            for label, arrivals in (("development", DEV_ARRIVALS_S),
                                    ("held_out_times", HELD_OUT_ARRIVALS_S)):
                event_rows = [row for row in selected
                              if row["future_arrival_s"] in arrivals]
                summary[f"{pressure:g}"][str(hold_s)][label] = {
                    "event_runs": len(event_rows),
                    "event_success_rate": mean(row["all_deadlines_met"] for row in event_rows),
                    "event_mean_first_action_ms": mean(
                        row["first_action_start_latency_ms"] for row in event_rows
                    ),
                    "hypothetical_mixture": {
                        f"p_{probability:g}": {
                            "expected_success_rate": round(
                                (1 - probability) * mean(row["all_deadlines_met"] for row in absent)
                                + probability * mean(row["all_deadlines_met"] for row in event_rows),
                                6,
                            ),
                            "expected_first_action_ms": round(
                                (1 - probability) * mean(row["first_action_start_latency_ms"]
                                                         for row in absent)
                                + probability * mean(row["first_action_start_latency_ms"]
                                                     for row in event_rows),
                                3,
                            ),
                        }
                        for probability in HYPOTHETICAL_EVENT_PROBABILITIES
                    },
                }
    report = {
        "schema_version": "c3-uncertain-arrival-grid-0.1",
        "status": "exploratory_controlled_arrivals_not_real_frequency_estimate",
        "same_saved_model_proposals": True,
        "new_api_calls": 0,
        "arrival_times_s": list(ARRIVALS_S),
        "hold_windows_s": list(HOLD_WINDOWS_S),
        "development_arrival_times_s": list(DEV_ARRIVALS_S),
        "held_out_arrival_times_s": list(HELD_OUT_ARRIVALS_S),
        "hypothetical_event_probabilities": list(HYPOTHETICAL_EVENT_PROBABILITIES),
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
