"""Controlled deadline/capacity matrix over the five C3 candidate templates.

This is a synthetic design experiment. It does not alter or certify the source
candidate episodes and does not use a model API.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from evaluate import ROOT, evaluate, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.dry_run import DryRunClient
from runtime.execution import run_closed_loop_episode


ARCHITECTURES = (
    "IndependentMultiAgent",
    "CentralSingleAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
)


def prepare_template(source: dict) -> tuple[dict, dict]:
    episode = deepcopy(source)
    episode["episode_id"] = f"{source['episode_id']}.deadline_matrix"
    episode["base_episode_id"] = source["episode_id"]
    episode["review_status"] = "generated_unreviewed_design_case"
    tasks = episode["task_stream"]
    if len(tasks) != 2:
        raise ValueError("matrix expects exactly two tasks")
    high = max(tasks, key=lambda item: item["priority"])
    low = min(tasks, key=lambda item: item["priority"])
    if high["priority"] == low["priority"]:
        raise ValueError("matrix needs distinct task priorities")
    high["release_at_ms"] = 100
    low["release_at_ms"] = 0
    groundings = {item["task_id"]: item for item in episode["action_grounding"]}
    high_duration = int(groundings[high["task_id"]]["duration_ms"])
    low_duration = int(groundings[low["task_id"]]["duration_ms"])
    high_earliest_finish = 800 + high_duration
    fifo_high_finish = max(800, 700 + low_duration) + high_duration
    if fifo_high_finish <= high_earliest_finish:
        raise ValueError("low action does not produce a deadline scheduling boundary")
    tight_deadline = (high_earliest_finish + fifo_high_finish) // 2
    high["completion_deadline_ms"] = tight_deadline
    info = {
        "source_episode": source["episode_id"],
        "high_task_id": high["task_id"],
        "low_task_id": low["task_id"],
        "high_duration_ms": high_duration,
        "low_duration_ms": low_duration,
        "high_earliest_finish_ms": high_earliest_finish,
        "fifo_high_finish_ms": fifo_high_finish,
        "tight_deadline_ms": tight_deadline,
        "safe_capacity_kw": round(sum(float(item["power_kw"]) for item in groundings.values()) + 0.1, 6),
    }
    return episode, info


def make_scenarios(source: dict) -> tuple[list[tuple[str, dict]], dict]:
    tight, info = prepare_template(source)
    safe_capacity = deepcopy(tight)
    safe_capacity["episode_id"] += ".safe_capacity"
    safe_capacity["home"]["resources"]["max_power_kw"] = info["safe_capacity_kw"]
    for rule in safe_capacity["conflict_rules"]:
        if rule["type"] == "C3":
            rule["capacity"] = info["safe_capacity_kw"]
    relaxed = deepcopy(tight)
    relaxed["episode_id"] += ".relaxed_deadline"
    for task in relaxed["task_stream"]:
        if task["task_id"] == info["high_task_id"]:
            task["completion_deadline_ms"] = info["fifo_high_finish_ms"] + 100
    return [
        ("tight_conflicting", tight),
        ("safe_capacity", safe_capacity),
        ("relaxed_deadline", relaxed),
    ], info


def outcome(episode: dict, trace: dict, result: dict, high_task_id: str) -> dict:
    actions = [event for event in trace["events"] if event["type"] == "action_effective"]
    high_action = next((event for event in actions if event.get("task_id") == high_task_id), None)
    high = next(task for task in episode["task_stream"] if task["task_id"] == high_task_id)
    high_finish = None if high_action is None else high_action["timestamp_ms"] + high_action["duration_ms"]
    deadline = high["completion_deadline_ms"]
    return {
        "process_valid_success_without_deadline": result["process_valid_success"],
        "conflict_count": sum(result["conflict_counts"].values()),
        "task_service_rate": result["task_service_rate"],
        "first_effective_action_ms": result["first_effective_action_latency_ms"],
        "legacy_goal_first_satisfied_ms": result["task_completion_time_ms"],
        "high_task_finished_ms": high_finish,
        "high_task_deadline_ms": deadline,
        "high_task_deadline_met": high_finish is not None and high_finish <= deadline,
    }


def full_information_priority_witness(episode: dict, fifo_trace: dict, high_id: str, low_id: str) -> tuple[dict, dict]:
    """Reorder the exact grounded FIFO actions after both proposals are known."""
    actions = {
        event["task_id"]: deepcopy(event)
        for event in fifo_trace["events"] if event["type"] == "action_effective"
    }
    if set(actions) != {high_id, low_id}:
        raise ValueError("witness needs both task actions")
    high = actions[high_id]
    low = actions[low_id]
    high["timestamp_ms"] = 800
    low["timestamp_ms"] = high["timestamp_ms"] + high["duration_ms"]
    trace = {
        "trace_id": f"{episode['episode_id']}.priority_witness",
        "episode_id": episode["episode_id"],
        "events": [high, low],
    }
    return trace, evaluate(episode, trace)


def run(output_path: Path) -> dict:
    rows: list[dict] = []
    cases: list[dict] = []
    for path in sorted((ROOT / "data" / "candidates").glob("*.json")):
        source = load_json(path)
        if source["task_family"] != "resource_capacity_conflict":
            continue
        scenarios, info = make_scenarios(source)
        cases.append(info)
        for scenario_name, episode in scenarios:
            traces = {}
            for architecture in ARCHITECTURES:
                trace, result = run_closed_loop_episode(
                    episode, DryRunClient(), architecture, INSTRUCTIONS, synthetic_latency=True
                )
                traces[architecture] = trace
                rows.append({
                    "source_episode": source["episode_id"],
                    "scenario": scenario_name,
                    "architecture": architecture,
                    **outcome(episode, trace, result, info["high_task_id"]),
                })
            if scenario_name == "tight_conflicting":
                trace, result = full_information_priority_witness(
                    episode, traces["ConstraintCoordinator"],
                    info["high_task_id"], info["low_task_id"],
                )
                rows.append({
                    "source_episode": source["episode_id"],
                    "scenario": scenario_name,
                    "architecture": "FullInformationPriorityWitness",
                    **outcome(episode, trace, result, info["high_task_id"]),
                })

    def count(scenario: str, architecture: str, key: str) -> int:
        return sum(bool(row[key]) for row in rows if row["scenario"] == scenario and row["architecture"] == architecture)

    summary = {
        "source_templates": len(cases),
        "scenario_count": len(cases) * 3,
        "architecture_scenario_runs": len(rows),
        "tight_fifo_process_valid": count("tight_conflicting", "ConstraintCoordinator", "process_valid_success_without_deadline"),
        "tight_fifo_deadlines_met": count("tight_conflicting", "ConstraintCoordinator", "high_task_deadline_met"),
        "tight_priority_witness_process_valid": count("tight_conflicting", "FullInformationPriorityWitness", "process_valid_success_without_deadline"),
        "tight_priority_witness_deadlines_met": count("tight_conflicting", "FullInformationPriorityWitness", "high_task_deadline_met"),
        "safe_capacity_independent_process_valid": count("safe_capacity", "IndependentMultiAgent", "process_valid_success_without_deadline"),
        "safe_capacity_fifo_deadlines_met": count("safe_capacity", "ConstraintCoordinator", "high_task_deadline_met"),
        "relaxed_deadline_fifo_deadlines_met": count("relaxed_deadline", "ConstraintCoordinator", "high_task_deadline_met"),
    }
    payload = {
        "experiment": "capacity_deadline_controlled_matrix",
        "status": "synthetic_unreviewed_design_experiment",
        "deadline_semantics": "task action effective_at + duration_ms <= completion_deadline_ms",
        "information_caveat": "The priority witness sees both grounded proposals, including one not yet returned when the low-priority proposal first becomes ready.",
        "cases": cases,
        "summary": summary,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "capacity_deadline_matrix_20260924.json",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
