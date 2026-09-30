"""C1/C3 design pilot with synthetic post-proposal coordination cost.

Conflict shares below are analytical mixtures of paired cases, not estimates
of how often household conflicts occur.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from make_representative_revision_drafts import make_drafts
from runtime.dry_run import DryRunClient
from runtime.event_simulator import run_event_simulation

ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "results" / "coordination_activation_boundary_pilot_20260927.json"
PROPOSAL_LATENCY_MS = 300
COORDINATION_DELAYS_MS = (0, 100, 300, 800)
CONFLICT_SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)
POLICIES = ("IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator")
PAIRS = {
    "C1": ("HC-PAIR-C1-HVAC-CONFLICT", "HC-PAIR-C1-HVAC-SAFE"),
    "C3": ("HC-PAIR-C3-HOME-POWER-OVER-CAPACITY",
           "HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL"),
}


class FixedLatencyClient(DryRunClient):
    def decide(self, request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        decision = super().decide(request, instructions)
        self.last_latency_ms = PROPOSAL_LATENCY_MS
        return decision


def run_cell(episode: dict[str, Any], policy: str, delay_ms: int) -> dict[str, Any]:
    trace, result = run_event_simulation(
        deepcopy(episode), FixedLatencyClient(), policy, "",
        coordination_delay_ms=delay_ms,
    )
    return {
        "episode_id": episode["episode_id"],
        "policy": policy,
        "coordination_delay_ms": result["coordination_delay_ms"],
        "proposal_times_ms": [event["timestamp_ms"] for event in trace["events"]
                              if event["type"] == "proposal_returned"],
        "decision_times_ms": [event["timestamp_ms"] for event in trace["events"]
                              if event["type"] == "coordination_decision"],
        "process_valid_success": bool(result["process_valid_success"]),
        "all_tasks_served": all(result["task_service"].values()),
        "conflict_count": sum(result["conflict_counts"].values()),
        "first_action_start_latency_ms": result["first_action_start_latency_ms"],
        "task_completion_time_ms": result["task_completion_time_ms"],
    }


def blend(safe: dict[str, Any], conflict: dict[str, Any], share: float) -> dict[str, float]:
    def expected(key: str) -> float:
        return round((1 - share) * float(safe[key]) + share * float(conflict[key]), 3)
    return {
        "safe_process_rate": expected("process_valid_success"),
        "all_tasks_served_rate": expected("all_tasks_served"),
        "first_action_start_ms": expected("first_action_start_latency_ms"),
        "task_completion_ms": expected("task_completion_time_ms"),
    }


def run_pilot() -> dict[str, Any]:
    drafts = {episode["episode_id"]: episode for episode in make_drafts()}
    cells: list[dict[str, Any]] = []
    for family, (conflict_id, safe_id) in PAIRS.items():
        for condition, episode_id in (("conflict", conflict_id), ("safe", safe_id)):
            for policy in POLICIES:
                delays = (0,) if policy == "IndependentMultiAgent" else COORDINATION_DELAYS_MS
                for delay in delays:
                    cells.append({"family": family, "condition": condition,
                                  **run_cell(drafts[episode_id], policy, delay)})

    mixtures: list[dict[str, Any]] = []
    for family in PAIRS:
        for policy in POLICIES:
            delays = (0,) if policy == "IndependentMultiAgent" else COORDINATION_DELAYS_MS
            for delay in delays:
                selected = [cell for cell in cells if cell["family"] == family
                            and cell["policy"] == policy
                            and cell["coordination_delay_ms"] == delay]
                if len(selected) != 2:
                    raise AssertionError(f"missing matched pair: {family}/{policy}/{delay}")
                by_condition = {cell["condition"]: cell for cell in selected}
                for share in CONFLICT_SHARES:
                    mixtures.append({
                        "family": family, "policy": policy,
                        "coordination_delay_ms": delay,
                        "assumed_conflict_share": share,
                        **blend(by_condition["safe"], by_condition["conflict"], share),
                    })

    payload = {
        "schema_version": "coordination-activation-boundary-pilot-0.1",
        "status": "synthetic_fixed_proposal_design_probe_not_household_frequency_estimate",
        "proposal_latency_ms": PROPOSAL_LATENCY_MS,
        "coordination_delays_ms": list(COORDINATION_DELAYS_MS),
        "assumed_conflict_shares": list(CONFLICT_SHARES),
        "api_calls": 0,
        "real_device_runs": 0,
        "cells": cells,
        "analytical_mixtures": mixtures,
    }
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run_pilot()
    print(json.dumps({"cells": len(result["cells"]),
                      "analytical_mixtures": len(result["analytical_mixtures"]),
                      "result": str(RESULT)}, ensure_ascii=False, indent=2))
