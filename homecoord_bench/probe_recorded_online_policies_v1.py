"""Replay blind EV/water model proposals through causal, simple online policies.

This compares scheduling decisions for fixed model outputs and measured API
latencies. All physical durations and power values remain synthetic.
"""

from __future__ import annotations

import json
from copy import deepcopy

from evaluate import ROOT
from make_paired_task_batch_v1 import build_batch
from run_online_deadline_baselines import POLICIES, online_schedule


SOURCE = ROOT / "results" / "paired_task_batch_v1_probe.json"
OUTPUT = ROOT / "results" / "recorded_online_policies_v1.json"
DEADLINE_SENSITIVITY_MS = (8000, 9000, 10000, 12000)


def run() -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    episodes = {
        episode["pair_condition"]: episode
        for episode in build_batch() if episode["pair_id"] == "C3-EV-WATER"
    }
    rows = []
    for source_row in source["rows"]:
        if source_row["pair_id"] != "C3-EV-WATER" or "conditions" not in source_row:
            continue
        records = source_row["model_records"]
        decisions = {
            "charge_ev": records["first_conflict"]["decision"],
            "heat_water": records["shared_local"]["decision"],
        }
        latencies = {
            "charge_ev": records["first_conflict"]["logical_latency_ms"],
            "heat_water": records["shared_local"]["logical_latency_ms"],
        }
        for condition, original in episodes.items():
            episode = deepcopy(original)
            departure = episode["initial_state"]["values"]["vehicle"]["departure_deadline_ms"]
            next(task for task in episode["task_stream"] if task["task_id"] == "charge_ev")[
                "completion_deadline_ms"
            ] = departure
            for policy in POLICIES:
                trace, result = online_schedule(
                    episode, policy, latency_by_task=latencies,
                    decision_by_task=decisions,
                )
                finish = result["task_action_finish_time_ms"]
                rows.append({
                    "pair_id": "C3-EV-WATER",
                    "condition": condition,
                    "repetition": source_row["repetition"],
                    "policy": policy,
                    "model_latency_ms": latencies,
                    "process_valid_success": result["process_valid_success"],
                    "task_service": result["task_service"],
                    "first_action_ms": result["first_effective_action_latency_ms"],
                    "charge_finish_ms": finish["charge_ev"],
                    "water_finish_ms": finish["heat_water"],
                    "departure_deadline_ms": departure,
                    "charge_deadline_met": result["task_deadline_met"]["charge_ev"],
                    "deadline_sensitivity": {
                        str(deadline): finish["charge_ev"] is not None
                        and finish["charge_ev"] <= deadline
                        for deadline in DEADLINE_SENSITIVITY_MS
                    },
                    "wait_for_released_task_count": sum(
                        event.get("decision") == "wait_for_released_task"
                        for event in trace["events"]
                    ),
                })
    payload = {
        "status": "exploratory_fixed_model_proposals_synthetic_devices",
        "source": str(SOURCE.relative_to(ROOT)),
        "deadline_sensitivity_ms": DEADLINE_SENSITIVITY_MS,
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    for condition in ("conflict", "control"):
        for policy in POLICIES:
            rows = [row for row in result["rows"]
                    if row["condition"] == condition and row["policy"] == policy]
            print(json.dumps({
                "condition": condition,
                "policy": policy,
                "safe": sum(row["process_valid_success"] for row in rows),
                "original_deadline_met": sum(row["charge_deadline_met"] for row in rows),
                "charge_finish_ms": [row["charge_finish_ms"] for row in rows],
                "water_finish_ms": [row["water_finish_ms"] for row in rows],
            }, ensure_ascii=False))
