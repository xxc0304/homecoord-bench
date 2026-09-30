"""Sweep fixed coordination hold windows across the future-urgent pair."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_future_pair import SOURCE, make_pair
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_staggered_release import release_order_records
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_hold_window_sweep_20260929.json"
HOLD_WINDOWS_MS = (0, 15_000, 30_000, 59_000, 60_000, 61_000, 120_000)


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
                ordered = release_order_records(episode, records)
                for hold_ms in HOLD_WINDOWS_MS:
                    configured = deepcopy(episode)
                    configured["simulation"]["hold_until_ms"] = hold_ms
                    client = MemoryReplayClient(deepcopy(ordered))
                    _, result = run_event_simulation(
                        configured, client, "FixedHoldCoordinator",
                        "saved proposals; fixed hold-window sweep",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "template_id": template_id,
                        "repetition": batch["repetition"],
                        "nominal_pressure": pressure,
                        "future_urgent": future_urgent,
                        "hold_until_ms": hold_ms,
                        "all_deadlines_met": result["all_deadlines_met"],
                        "all_tasks_served": all(result["task_service"].values()),
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    })
    summary: dict[str, Any] = {}
    for pressure in PRESSURES:
        summary[f"{pressure:g}"] = {}
        for future_urgent in (False, True):
            key = "present" if future_urgent else "absent"
            summary[f"{pressure:g}"][key] = {}
            for hold_ms in HOLD_WINDOWS_MS:
                subset = [row for row in rows if row["nominal_pressure"] == pressure
                          and row["future_urgent"] == future_urgent
                          and row["hold_until_ms"] == hold_ms]
                summary[f"{pressure:g}"][key][str(hold_ms)] = {
                    "runs": len(subset),
                    "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                    "median_first_action_start_latency_ms": median(
                        row["first_action_start_latency_ms"] for row in subset
                    ),
                }
    report = {
        "schema_version": "c3-hold-window-sweep-0.1",
        "status": "exploratory_window_sweep_on_saved_proposals",
        "new_api_calls": 0,
        "hold_windows_ms": list(HOLD_WINDOWS_MS),
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
