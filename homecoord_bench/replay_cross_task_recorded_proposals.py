"""Cross-template, common-gate replay of previously recorded model proposals.

The same sampled decisions and logical arrival times are reused for every
policy. This is an exploratory policy comparison, not fresh model inference.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from evaluate import ROOT
from make_paired_task_batch_v1 import make_blinds, make_hvac
from probe_physical_capacity_v2 import make_episode as make_physical_episode
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


SOURCES = {
    "paired": ROOT / "results" / "paired_task_batch_v1_probe.json",
    "physical": ROOT / "results" / "physical_capacity_v2.json",
}
OUTPUT = ROOT / "results" / "cross_task_recorded_proposal_replay_20260928.json"
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator",
)


def _episode_and_records(pair_id: str, condition: str, row: dict) -> tuple[dict, list[dict]]:
    if pair_id == "C1-HVAC":
        episode = make_hvac(condition == "conflict")
    elif pair_id == "C1-BLINDS":
        episode = make_blinds(condition == "conflict")
    elif pair_id == "C3-EV-WATER-PHYSICAL":
        episode = make_physical_episode(condition)
        episode["home"]["resources"]["task_power_bounds_kw"] = {
            "charge_ev": 4.0, "heat_water": 3.0,
        }
    else:
        raise ValueError(pair_id)
    if pair_id.startswith("C1"):
        stored = row["model_records"]
        by_task = {
            episode["task_stream"][0]["task_id"]: stored[
                "first_conflict" if condition == "conflict" else "first_control"
            ],
            episode["task_stream"][1]["task_id"]: stored["shared_local"],
        }
    else:
        by_task = row["model_records"]
    return episode, [by_task[task["task_id"]] for task in episode["task_stream"]]


def run() -> dict:
    source_bytes = {key: path.read_bytes() for key, path in SOURCES.items()}
    sources = {key: json.loads(value) for key, value in source_bytes.items()}
    rows = []
    for pair_id in ("C1-HVAC", "C1-BLINDS", "C3-EV-WATER-PHYSICAL"):
        source_rows = (sources["physical"]["rows"] if pair_id.startswith("C3") else
                       [row for row in sources["paired"]["rows"] if row["pair_id"] == pair_id])
        for source_row in source_rows:
            if "model_records" not in source_row:
                continue
            for condition in ("conflict", "control"):
                episode, records = _episode_and_records(pair_id, condition, source_row)
                task_ids = [task["task_id"] for task in episode["task_stream"]]
                assert len(task_ids) == len(records)
                for policy in POLICIES:
                    client = MemoryReplayClient(deepcopy(records))
                    trace, result = run_event_simulation(
                        deepcopy(episode), client, policy, "recorded-proposal replay",
                        shared_safety_gate=True,
                    )
                    client.assert_consumed()
                    rows.append({
                        "pair_id": pair_id,
                        "condition": condition,
                        "source_repetition": source_row["repetition"],
                        "policy": policy,
                        "model_latency_by_task_ms": result["model_latency_by_task_ms"],
                        "proposal_response_type_by_task": {
                            task_id: record["decision"]["response_type"]
                            for task_id, record in zip(task_ids, records)
                        },
                        "first_proposal_returned_task": next(
                            (event["task_id"] for event in trace["events"]
                             if event["type"] == "proposal_returned"), None
                        ),
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "first_goal_progress_latency_ms": result["first_goal_progress_latency_ms"],
                        "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                        "task_service": result["task_service"],
                        "task_deadline_met": result["task_deadline_met"],
                        "all_deadlines_met": result["all_deadlines_met"],
                        "final_goal_success": result["final_goal_success"],
                        "process_valid_success": result["process_valid_success"],
                        "state_constraint_violation_episode_count": result[
                            "state_constraint_violation_episode_count"
                        ],
                        "shared_safety_gate_rejection_count": result[
                            "shared_safety_gate_rejection_count"
                        ],
                        "rejection_reasons": [event["reason"] for event in trace["events"]
                                              if event["type"] == "action_rejected"],
                        "started_task_ids": [event["task_id"] for event in trace["events"]
                                             if event["type"] == "action_started"],
                    })
    report = {
        "schema_version": "cross-task-recorded-proposal-replay-0.1",
        "status": "exploratory_synthetic_tasks_replayed_model_proposals_not_independent_homes",
        "source_sha256": {key: hashlib.sha256(value).hexdigest()
                          for key, value in source_bytes.items()},
        "source_model": {key: sources[key].get("model") for key in SOURCES},
        "same_recorded_decisions_and_latencies_across_policies": True,
        "same_shared_safety_gate_across_policies": True,
        "new_api_calls": 0,
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps({"rows": len(report["rows"]), "output": str(OUTPUT)}, ensure_ascii=False))
