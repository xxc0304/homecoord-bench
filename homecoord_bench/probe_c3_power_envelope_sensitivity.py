"""Sensitivity of C3 replay to actual load below the nameplate envelope."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_c3_non_nested_templates import POLICIES, TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
OUTPUT = ROOT / "results" / "c3_power_envelope_sensitivity_20260929.json"
LOAD_FACTORS = (0.5, 0.75, 1.0)


def scale_load(episode: dict[str, Any], factor: float,
               information_mode: str) -> dict[str, Any]:
    if information_mode not in {"actual_known", "rated_bound_only"}:
        raise ValueError(information_mode)
    copy = deepcopy(episode)
    for task in copy["task_stream"]:
        task["action_template"]["power_kw"] = round(
            task["action_template"]["power_kw"] * factor, 6
        )
    for action in copy["action_grounding"]:
        action["power_kw"] = round(action["power_kw"] * factor, 6)
    if information_mode == "actual_known":
        bounds = copy["home"]["resources"]["task_power_bounds_kw"]
        for task_id in bounds:
            bounds[task_id] = round(bounds[task_id] * factor, 6)
    copy["episode_id"] += f"-LOAD-{factor:g}-{information_mode}"
    copy["source_type"] = "controlled_load_factor_sensitivity"
    copy["review_status"] = "exploratory_not_frozen"
    copy["resource_pressure"]["actual_load_factor_vs_rating"] = factor
    copy["resource_pressure"]["information_mode"] = information_mode
    copy["resource_pressure"]["effective_load_to_capacity_ratio"] = round(
        copy["resource_pressure"]["load_to_capacity_ratio"] * factor, 6
    )
    return copy


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for batch in payload["batches"]:
        template_id = batch["template_id"]
        specs = TEMPLATES[template_id]
        records = batch["sample"]["records"]
        if set(records) != {task.task_id for task in specs}:
            continue
        for pressure in PRESSURES:
            base = make_episode_from_specs(template_id, specs, pressure)
            for factor in LOAD_FACTORS:
                for information_mode in ("actual_known", "rated_bound_only"):
                    episode = scale_load(base, factor, information_mode)
                    ordered = [records[task["task_id"]] for task in episode["task_stream"]]
                    for policy in POLICIES:
                        client = MemoryReplayClient(deepcopy(ordered))
                        _, result = run_event_simulation(
                            deepcopy(episode), client, policy,
                            "recorded parallel proposals; controlled load factor",
                            shared_safety_gate=True,
                        )
                        client.assert_consumed()
                        rows.append({
                            "template_id": template_id,
                            "repetition": batch["repetition"],
                            "nominal_pressure": pressure,
                            "load_factor": factor,
                            "information_mode": information_mode,
                            "effective_pressure": round(pressure * factor, 6),
                            "policy": policy,
                            "all_tasks_served": all(result["task_service"].values()),
                            "all_deadlines_met": result["all_deadlines_met"],
                            "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        })
    summary: dict[str, Any] = {}
    for pressure in PRESSURES:
        for factor in LOAD_FACTORS:
            for information_mode in ("actual_known", "rated_bound_only"):
                key = f"rho_{pressure:g}_factor_{factor:g}_{information_mode}"
                summary[key] = {
                    "effective_pressure": round(pressure * factor, 6),
                    "by_policy": {},
                }
                for policy in POLICIES:
                    subset = [row for row in rows
                              if row["nominal_pressure"] == pressure
                              and row["load_factor"] == factor
                              and row["information_mode"] == information_mode
                              and row["policy"] == policy]
                    summary[key]["by_policy"][policy] = {
                        "runs": len(subset),
                        "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset),
                        "all_tasks_served": sum(row["all_tasks_served"] for row in subset),
                    }
    report = {
        "schema_version": "c3-power-envelope-sensitivity-0.1",
        "status": "exploratory_uniform_load_factor_not_measured_trace",
        "load_factors": list(LOAD_FACTORS),
        "information_modes": ["actual_known", "rated_bound_only"],
        "same_saved_model_proposals": True,
        "api_calls": 0,
        "rows": rows,
        "summary": summary,
        "interpretation": (
            "Nameplate power is an upper-bound planning envelope. Uniform factors "
            "are controlled counterfactuals, not measured appliance duty cycles. "
            "The two information modes separate exact derated bounds from a coordinator "
            "that retains only nameplate bounds."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
