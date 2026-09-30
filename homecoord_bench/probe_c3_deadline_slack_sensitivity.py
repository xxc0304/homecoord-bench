"""Replay saved concurrent model proposals under controlled deadline slack changes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from make_c3_review_candidates import feasible_schedule
from probe_c3_non_nested_templates import POLICIES, TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
OUTPUT = ROOT / "results" / "c3_deadline_slack_sensitivity_20260929.json"
SLACK_FACTORS = (0.5, 0.75, 1.0, 1.25, 1.5)


def change_deadline_slack(episode: dict[str, Any], factor: float) -> dict[str, Any]:
    """Keep cycles and priorities fixed; scale each task's service slack."""
    if factor <= 0:
        raise ValueError("slack factor must be positive")
    modified = deepcopy(episode)
    for task in modified["task_stream"]:
        duration = int(task["action_template"]["duration_ms"])
        original = int(task["completion_deadline_ms"])
        if original < duration:
            raise ValueError("base episode has an impossible individual deadline")
        task["completion_deadline_ms"] = duration + round((original - duration) * factor)
        task["goal"] = (
            f"Complete {task['task_id']} by "
            f"{task['completion_deadline_ms'] / 60000:g} minutes."
        )
    modified["episode_id"] += f"-SLACK-{factor:g}"
    modified["source_type"] = "controlled_deadline_slack_sensitivity"
    modified["review_status"] = "exploratory_not_frozen"
    modified["scenario_assumptions"]["deadline_semantics"] = (
        "researcher-controlled service slack, not observed user deadline distribution"
    )
    return modified


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    saved = json.loads(source.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for batch in saved["batches"]:
        template_id = batch["template_id"]
        specs = TEMPLATES[template_id]
        records = batch["sample"]["records"]
        if set(records) != {task.task_id for task in specs}:
            raise ValueError(f"incomplete model batch: {template_id}/{batch['repetition']}")
        for pressure in PRESSURES:
            base = make_episode_from_specs(template_id, specs, pressure)
            for factor in SLACK_FACTORS:
                episode = change_deadline_slack(base, factor)
                ideal = feasible_schedule(episode)
                ordered = [records[task["task_id"]] for task in episode["task_stream"]]
                for policy in POLICIES:
                    client = MemoryReplayClient(deepcopy(ordered))
                    _, result = run_event_simulation(
                        deepcopy(episode), client, policy,
                        "saved parallel proposals; controlled deadline slack",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "template_id": template_id,
                        "repetition": batch["repetition"],
                        "pressure": pressure,
                        "slack_factor": factor,
                        "ideal_feasible": ideal is not None,
                        "policy": policy,
                        "all_tasks_served": all(result["task_service"].values()),
                        "all_deadlines_met": result["all_deadlines_met"],
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    })
    summary: dict[str, Any] = {}
    for template_id in TEMPLATES:
        summary[template_id] = {}
        for pressure in PRESSURES:
            summary[template_id][f"{pressure:g}"] = {}
            for factor in SLACK_FACTORS:
                subset = [row for row in rows if row["template_id"] == template_id
                          and row["pressure"] == pressure and row["slack_factor"] == factor]
                key = f"{factor:g}"
                summary[template_id][f"{pressure:g}"][key] = {
                    "ideal_feasible": subset[0]["ideal_feasible"],
                    "by_policy": {
                        policy: {
                            "runs": len([row for row in subset if row["policy"] == policy]),
                            "all_deadlines_met": sum(row["all_deadlines_met"] for row in subset
                                                     if row["policy"] == policy),
                        }
                        for policy in POLICIES
                    },
                }
    report = {
        "schema_version": "c3-deadline-slack-sensitivity-0.1",
        "status": "exploratory_controlled_deadlines_not_observational_distribution",
        "same_saved_model_proposals": True,
        "api_calls": 0,
        "slack_factors": list(SLACK_FACTORS),
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
