"""Counterfactually reverse saved response latencies to test async-order effects."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluate import ROOT, load_json
from runtime.event_simulator import POLICY_DESCRIPTIONS, run_event_simulation
from runtime.replay_client import MemoryReplayClient


SOURCE = ROOT / "results" / "physical_capacity_v2.json"
EPISODE_DIR = ROOT / "data" / "pilot_physical_v2"
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
)
LATENCY_MODES = ("recorded", "reversed")
CONDITIONS = ("conflict", "control")


def _records(model_records: dict[str, Any], latency_mode: str) -> list[dict[str, Any]]:
    charge = model_records["charge_ev"]
    water = model_records["heat_water"]
    charge_latency = int(charge["logical_latency_ms"])
    water_latency = int(water["logical_latency_ms"])
    if latency_mode == "reversed":
        charge_latency, water_latency = water_latency, charge_latency
    elif latency_mode != "recorded":
        raise ValueError(f"unsupported latency mode: {latency_mode}")
    return [
        {"decision": charge["decision"], "logical_latency_ms": charge_latency},
        {"decision": water["decision"], "logical_latency_ms": water_latency},
    ]


def run(output_path: Path) -> dict[str, Any]:
    source = load_json(SOURCE)
    episodes = {
        condition: load_json(EPISODE_DIR / f"{condition}.json")
        for condition in CONDITIONS
    }
    rows = []
    for sample in source["rows"]:
        model_records = sample.get("model_records")
        if not model_records or not {"charge_ev", "heat_water"}.issubset(model_records):
            continue
        for latency_mode in LATENCY_MODES:
            records = _records(model_records, latency_mode)
            for condition, episode in episodes.items():
                for policy in POLICIES:
                    replay = MemoryReplayClient(records)
                    trace, result = run_event_simulation(episode, replay, policy, "")
                    replay.assert_consumed()
                    returned = [
                        event["task_id"] for event in trace["events"]
                        if event["type"] == "proposal_returned"
                    ]
                    started = [
                        event["task_id"] for event in trace["events"]
                        if event["type"] == "action_started"
                    ]
                    rows.append({
                        "repetition": sample["repetition"],
                        "latency_mode": latency_mode,
                        "condition": condition,
                        "policy": policy,
                        "proposal_return_order": returned,
                        "action_start_order": started,
                        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                        "first_goal_progress_latency_ms": result["first_goal_progress_latency_ms"],
                        "process_valid_success": result["process_valid_success"],
                        "timely_process_valid_success": result["timely_process_valid_success"],
                        "task_deadline_met": result["task_deadline_met"],
                        "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                        "task_service_rate": result["task_service_rate"],
                        "conflict_counts": result["conflict_counts"],
                    })
    report = {
        "schema_version": "proposal-order-sensitivity-0.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "saved DeepSeek decisions and measured per-task latencies",
        "network_calls": 0,
        "counterfactual": (
            "reversed mode swaps the two saved per-task latencies while keeping decisions fixed; "
            "it is an isolation probe, not a newly measured model run"
        ),
        "physical_assumptions": load_json(SOURCE)["assumptions"],
        "policies": list(POLICIES),
        "policy_descriptions": {policy: POLICY_DESCRIPTIONS[policy] for policy in POLICIES},
        "conditions": list(CONDITIONS),
        "latency_modes": list(LATENCY_MODES),
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
        default=ROOT / "results" / "proposal_order_sensitivity_20260926.json",
    )
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({
        "output": str(args.output), "runs": report["run_count"],
        "network_calls": report["network_calls"], "latency_modes": report["latency_modes"],
    }, ensure_ascii=False, indent=2))
