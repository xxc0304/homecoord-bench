"""A synthetic feasibility witness for deadline-aware capacity scheduling.

The witness is derived from HC-M13. It is not one of the reviewed benchmark
episodes and does not claim physical calibration or a new scheduling method.
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


def make_probe(*, capacity_kw: float = 6.0, deadline_ms: int = 9000) -> dict:
    episode = deepcopy(load_json(ROOT / "data" / "candidates" / "HC-M13.json"))
    episode["episode_id"] = f"HC-PROBE-C3-cap{capacity_kw:g}-deadline{deadline_ms}"
    episode["source_type"] = "synthetic_design_probe"
    episode["review_status"] = "unreviewed_probe"
    episode["home"]["resources"]["max_power_kw"] = capacity_kw
    for rule in episode["conflict_rules"]:
        if rule["type"] == "C3":
            rule["capacity"] = capacity_kw
    for task in episode["task_stream"]:
        if task["task_id"] == "heat_water":
            task["release_at_ms"] = 0
        elif task["task_id"] == "charge_ev":
            task["release_at_ms"] = 100
            task["completion_deadline_ms"] = deadline_ms
    episode["initial_state"]["values"]["vehicle"]["departure_deadline_ms"] = deadline_ms
    return episode


def score(episode: dict, trace: dict, result: dict) -> dict:
    actions = [event for event in trace["events"] if event["type"] == "action_effective"]
    charger = next((event for event in actions if event.get("task_id") == "charge_ev"), None)
    deadline = next(task["completion_deadline_ms"] for task in episode["task_stream"] if task["task_id"] == "charge_ev")
    charge_finished = None if charger is None else charger["timestamp_ms"] + charger["duration_ms"]
    return {
        "process_valid_success": result["process_valid_success"],
        "final_goal_success": result["final_goal_success"],
        "conflict_counts": result["conflict_counts"],
        "task_service_rate": result["task_service_rate"],
        "first_effective_action_ms": result["first_effective_action_latency_ms"],
        "legacy_first_goal_satisfaction_ms": result["task_completion_time_ms"],
        "all_executed_actions_finished_ms": max(
            (event["timestamp_ms"] + event["duration_ms"] for event in actions), default=None
        ),
        "charge_ev_finished_ms": charge_finished,
        "charge_ev_deadline_ms": deadline,
        "charge_ev_deadline_met": charge_finished is not None and charge_finished <= deadline,
    }


def priority_first_witness(episode: dict, fifo_trace: dict) -> tuple[dict, dict]:
    """Reorder the two already-grounded actions to prove schedule feasibility."""
    actions = {
        event["task_id"]: deepcopy(event)
        for event in fifo_trace["events"] if event["type"] == "action_effective"
    }
    if set(actions) != {"charge_ev", "heat_water"}:
        raise ValueError("probe expected exactly one grounded action per task")
    # Both proposals have been collected. Holding the water task for 100 ms
    # lets the higher-priority charging task start once its proposal is ready.
    actions["charge_ev"]["timestamp_ms"] = 800
    actions["heat_water"]["timestamp_ms"] = 800 + actions["charge_ev"]["duration_ms"]
    trace = {
        "trace_id": f"{episode['episode_id']}.priority_first_feasibility_witness",
        "episode_id": episode["episode_id"],
        "events": [actions["charge_ev"], actions["heat_water"]],
    }
    return trace, evaluate(episode, trace)


def run(output_path: Path) -> dict:
    scenarios = [
        ("tight_conflicting", make_probe(capacity_kw=6.0, deadline_ms=9000)),
        ("capacity_safe_control", make_probe(capacity_kw=7.1, deadline_ms=9000)),
        ("relaxed_deadline_control", make_probe(capacity_kw=6.0, deadline_ms=10000)),
    ]
    rows = []
    for name, episode in scenarios:
        traces = {}
        for architecture in ("IndependentMultiAgent", "CentralSingleAgent", "RuleCoordinator", "ConstraintCoordinator"):
            trace, result = run_closed_loop_episode(
                episode, DryRunClient(), architecture, INSTRUCTIONS, synthetic_latency=True
            )
            traces[architecture] = trace
            rows.append({"scenario": name, "architecture": architecture, **score(episode, trace, result)})
        if name == "tight_conflicting":
            witness_trace, witness_result = priority_first_witness(episode, traces["ConstraintCoordinator"])
            rows.append({
                "scenario": name,
                "architecture": "PriorityFirstFeasibilityWitness",
                **score(episode, witness_trace, witness_result),
            })

    payload = {
        "experiment": "capacity_deadline_design_probe",
        "status": "synthetic_unreviewed_feasibility_witness",
        "source_episode": "HC-M13",
        "changes": {
            "water_task_release_ms": 0,
            "charging_task_release_ms": 100,
            "charging_deadline_ms": 9000,
            "safe_capacity_kw": 7.1,
            "relaxed_deadline_ms": 10000,
            "deadline_semantics": "required charging action effective_at + duration_ms <= deadline_ms",
        },
        "caveats": [
            "Action duration, power and model latency are synthetic placeholders.",
            "The priority-first witness reorders known proposals; it is a feasibility witness, not an implemented agent baseline.",
            "The existing evaluator does not enforce deadline_ms; deadline_met is calculated explicitly in this probe.",
        ],
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "capacity_deadline_design_probe_20260924.json",
    )
    args = parser.parse_args()
    payload = run(args.output)
    print(json.dumps(payload["rows"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
