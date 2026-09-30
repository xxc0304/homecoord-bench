"""Sweep EV departure deadlines over saved model proposals in event replay."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluate import ROOT, load_json
from runtime.event_simulator import POLICY_DESCRIPTIONS, run_event_simulation
from runtime.replay_client import MemoryReplayClient


SOURCE = ROOT / "results" / "physical_capacity_v2.json"
DEADLINES_MS = (18_000_000, 18_600_000, 19_200_000, 20_400_000, 21_600_000)
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
)
CONDITIONS = ("conflict", "control")


def _records(model_records: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"decision": model_records[task_id]["decision"],
         "logical_latency_ms": model_records[task_id]["logical_latency_ms"]}
        for task_id in ("charge_ev", "heat_water")
    ]


def run(output_path: Path) -> dict[str, Any]:
    source = load_json(SOURCE)
    episodes = {
        condition: load_json(ROOT / "data" / "pilot_physical_v2" / f"{condition}.json")
        for condition in CONDITIONS
    }
    rows = []
    for sample in source["rows"]:
        if "model_records" not in sample or "outcomes" not in sample:
            continue
        replay_records = _records(sample["model_records"])
        for condition, base_episode in episodes.items():
            for deadline in DEADLINES_MS:
                episode = deepcopy(base_episode)
                episode["initial_state"]["values"]["vehicle"]["departure_deadline_ms"] = deadline
                charge_task = next(task for task in episode["task_stream"] if task["task_id"] == "charge_ev")
                charge_task["completion_deadline_ms"] = deadline
                for policy in POLICIES:
                    replay = MemoryReplayClient(replay_records)
                    trace, result = run_event_simulation(episode, replay, policy, "")
                    replay.assert_consumed()
                    returned_order = [
                        event["task_id"] for event in trace["events"]
                        if event["type"] == "proposal_returned"
                    ]
                    rows.append({
                        "repetition": sample["repetition"],
                        "condition": condition,
                        "ev_deadline_ms": deadline,
                        "policy": policy,
                        "proposal_return_order": returned_order,
                        "process_valid_success": result["process_valid_success"],
                        "timely_process_valid_success": result["timely_process_valid_success"],
                        "task_service_rate": result["task_service_rate"],
                        "task_deadline_met": result["task_deadline_met"],
                        "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                        "conflict_counts": result["conflict_counts"],
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "first_goal_progress_latency_ms": result["first_goal_progress_latency_ms"],
                        "first_effective_action_latency_ms": result["first_effective_action_latency_ms"],
                        "completion_constraint_violation_count": result["completion_constraint_violation_count"],
                    })
    report = {
        "schema_version": "event-deadline-sensitivity-0.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "saved DeepSeek v2 proposal records; no new API requests",
        "network_calls": 0,
        "proposal_replay": "same decisions and measured logical latencies across conditions and policies",
        "physical_assumptions": source["assumptions"],
        "deadline_sweep_ms": list(DEADLINES_MS),
        "policies": list(POLICIES),
        "policy_descriptions": {policy: POLICY_DESCRIPTIONS[policy] for policy in POLICIES},
        "run_count": len(rows),
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "event_deadline_sensitivity_20260926.json",
    )
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({
        "output": str(args.output), "runs": report["run_count"],
        "network_calls": report["network_calls"],
        "deadlines_ms": report["deadline_sweep_ms"],
    }, ensure_ascii=False, indent=2))
