"""C1/C3 fixed-proposal pilot with an identical safety veto for every policy.

The gate rejects unsafe physical starts; it does not defer or retry. Results
therefore isolate whether advance coordination preserves task service when a
simple safety floor is already present. All parameters remain synthetic.
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
RESULT = ROOT / "results" / "coordination_shared_safety_pilot_20260927.json"
EPISODE_IDS = (
    "HC-PAIR-C1-HVAC-CONFLICT",
    "HC-PAIR-C1-HVAC-SAFE",
    "HC-PAIR-C3-HOME-POWER-OVER-CAPACITY",
    "HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT",
    "HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL",
)
POLICIES = ("IndependentMultiAgent", "RuleCoordinator",
            "ConstraintCoordinator", "CentralSingleAgent")
COORDINATION_DELAYS_MS = (0, 300)


class FixedLatencyClient(DryRunClient):
    def decide(self, request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        decision = super().decide(request, instructions)
        self.last_latency_ms = 300
        return decision


def run_pilot() -> dict[str, Any]:
    episodes = {episode["episode_id"]: episode for episode in make_drafts()}
    cells = []
    for episode_id in EPISODE_IDS:
        for policy in POLICIES:
            delays = COORDINATION_DELAYS_MS if policy in {
                "RuleCoordinator", "ConstraintCoordinator"
            } else (0,)
            for delay in delays:
                trace, result = run_event_simulation(
                    deepcopy(episodes[episode_id]), FixedLatencyClient(), policy, "",
                    coordination_delay_ms=delay, shared_safety_gate=True,
                )
                service_finish_times = result["task_action_finish_time_ms"]
                cells.append({
                    "episode_id": episode_id,
                    "policy": policy,
                    "coordination_delay_ms": delay,
                    "final_goal_success": result["final_goal_success"],
                    "process_valid_success": result["process_valid_success"],
                    "task_service": result["task_service"],
                    "all_tasks_served": all(result["task_service"].values()),
                    "task_action_finish_time_ms": service_finish_times,
                    "all_required_actions_completed_at_ms": (
                        max(service_finish_times.values())
                        if service_finish_times and all(
                            value is not None for value in service_finish_times.values()
                        ) else None
                    ),
                    "conflict_counts": result["conflict_counts"],
                    "state_constraint_violation_episode_count": result[
                        "state_constraint_violation_episode_count"
                    ],
                    "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                    "rejection_reasons": [event["reason"] for event in trace["events"]
                                          if event["type"] == "action_rejected"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "final_goal_completion_time_ms": result["task_completion_time_ms"],
                })
    payload = {
        "schema_version": "coordination-shared-safety-pilot-0.1",
        "status": "synthetic_fixed_proposal_author_side_probe_not_reviewed_benchmark",
        "proposal_latency_ms": 300,
        "safety_gate": "same start-time veto for declared action conflicts, capacity, and projected state constraints; no retry",
        "policies": list(POLICIES),
        "coordination_delays_ms": list(COORDINATION_DELAYS_MS),
        "api_calls": 0,
        "real_device_runs": 0,
        "cells": cells,
    }
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run_pilot()
    print(json.dumps({"cells": len(result["cells"]), "result": str(RESULT)},
                     ensure_ascii=False, indent=2))
