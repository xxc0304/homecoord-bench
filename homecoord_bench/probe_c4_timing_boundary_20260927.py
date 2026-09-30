"""Probe stale-state episode behavior around the event/action-start boundary.

This is a deterministic offline experiment. It injects fixed proposal latencies
into DryRunClient; the latency values are test factors, not model measurements.
No model API or device is used.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


BENCH_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import goals_satisfied, set_path  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402


CANDIDATE_DIR = BENCH_ROOT / "data" / "candidates"
OUTPUT_PATH = BENCH_ROOT / "results" / "c4_timing_boundary_probe_20260927.json"
EPISODE_IDS = ["HC-M16", "HC-M17", "HC-M18", "HC-M19", "HC-M20"]
POLICIES = [
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
]
PROPOSAL_LATENCIES_MS = [300, 400, 600]
REPETITIONS = 3
DEFAULT_COMMAND_LATENCY_MS = 100


class FixedLatencyDryRun(DryRunClient):
    """Return the deterministic template action with an injected response delay."""

    def __init__(self, latency_ms: int):
        self.latency_ms = latency_ms

    def decide(self, agent_request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        decision = super().decide(agent_request, instructions)
        self.last_latency_ms = self.latency_ms
        return decision


def load_episode(episode_id: str) -> tuple[dict[str, Any], str]:
    path = CANDIDATE_DIR / f"{episode_id}.json"
    raw = path.read_bytes()
    episode = json.loads(raw.decode("utf-8"))
    if episode.get("episode_id") != episode_id:
        raise ValueError(f"episode id mismatch in {path}")
    return episode, hashlib.sha256(raw).hexdigest()


def environment_only_goal_success(episode: dict[str, Any]) -> bool:
    state = json.loads(json.dumps(episode["initial_state"]["values"]))
    for event in sorted(episode.get("exogenous_events", []), key=lambda item: item["at_ms"]):
        for path, value in event.get("patch", {}).items():
            set_path(state, path, value)
    return goals_satisfied(state, episode.get("goals", []))


def compact_events(trace: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields = (
        "task_id", "timestamp_ms", "reason", "decision", "defer_until_ms",
        "state_version", "new_state_version", "source",
        "constraint_violation_started", "constraint_violation_resolved", "patch",
    )
    types = {
        "state_update", "proposal_returned", "coordination_decision",
        "action_started", "action_completed", "action_rejected",
    }
    return {
        kind: [
            {key: event[key] for key in fields if key in event}
            for event in trace["events"] if event["type"] == kind
        ]
        for kind in sorted(types)
    }


def run_probe() -> dict[str, Any]:
    episode_payloads = {episode_id: load_episode(episode_id) for episode_id in EPISODE_IDS}
    rows: list[dict[str, Any]] = []
    for episode_id in EPISODE_IDS:
        episode, sha256 = episode_payloads[episode_id]
        event_times = [item["at_ms"] for item in episode.get("exogenous_events", [])]
        for latency_ms in PROPOSAL_LATENCIES_MS:
            for policy in POLICIES:
                for repetition in range(1, REPETITIONS + 1):
                    trace, metrics = run_event_simulation(
                        episode,
                        FixedLatencyDryRun(latency_ms),
                        policy,
                        instructions="Deterministic C4 timing-boundary probe.",
                    )
                    started = [
                        {key: event[key] for key in ("task_id", "timestamp_ms", "operation") if key in event}
                        for event in trace["events"] if event["type"] == "action_started"
                    ]
                    completed = [
                        {key: event[key] for key in ("task_id", "timestamp_ms", "operation") if key in event}
                        for event in trace["events"] if event["type"] == "action_completed"
                    ]
                    rejected = [
                        {key: event[key] for key in ("task_id", "timestamp_ms", "reason") if key in event}
                        for event in trace["events"] if event["type"] == "action_rejected"
                    ]
                    rows.append({
                        "episode_id": episode_id,
                        "episode_sha256": sha256,
                        "policy": policy,
                        "proposal_latency_factor_ms": latency_ms,
                        "default_command_latency_ms": int(
                            episode.get("simulation", {}).get(
                                "command_latency_ms", DEFAULT_COMMAND_LATENCY_MS
                            )
                        ),
                        "repetition": repetition,
                        "external_event_times_ms": event_times,
                        "external_events_alone_satisfy_goal": environment_only_goal_success(episode),
                        "final_goal_success": metrics["final_goal_success"],
                        "process_valid_success": metrics["process_valid_success"],
                        "conflict_counts": metrics["conflict_counts"],
                        "task_service": metrics["task_service"],
                        "task_action_finish_time_ms": metrics["task_action_finish_time_ms"],
                        "precondition_violations_at_start": metrics.get("precondition_violations_at_start", 0),
                        "stale_at_action_start_count": metrics.get("stale_at_action_start_count", 0),
                        "unsafe_precondition_rejection_count": metrics.get("unsafe_precondition_rejection_count", 0),
                        "in_flight_precondition_invalidated_action_count": metrics.get(
                            "in_flight_precondition_invalidated_action_count", 0
                        ),
                        "in_flight_precondition_invalidations": metrics.get(
                            "in_flight_precondition_invalidations", []
                        ),
                        "unsafe_state_onset_during_action_count": metrics.get(
                            "unsafe_state_onset_during_action_count", 0
                        ),
                        "unsafe_state_onsets_during_action": metrics.get(
                            "unsafe_state_onsets_during_action", []
                        ),
                        "constraint_violation_episode_count": metrics.get("state_constraint_violation_episode_count", 0),
                        "constraint_violation_duration_ms": metrics.get("state_constraint_violation_duration_ms", 0),
                        "first_action_start_latency_ms": metrics.get("first_action_start_latency_ms"),
                        "first_goal_progress_latency_ms": metrics.get("first_goal_progress_latency_ms"),
                        "actions_started": started,
                        "actions_completed": completed,
                        "actions_rejected": rejected,
                        "event_trace": compact_events(trace),
                    })

    # Compare every repeat group exactly; these are scripted deterministic runs.
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["episode_id"], row["policy"], row["proposal_latency_factor_ms"])
        groups.setdefault(key, []).append(row)
    deterministic_groups = 0
    for group in groups.values():
        signatures = {
            json.dumps(
                {key: value for key, value in row.items() if key != "repetition"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            for row in group
        }
        if len(signatures) == 1:
            deterministic_groups += 1

    return {
        "schema_version": "homecoord-c4-timing-boundary-probe-0.1",
        "date": "2026-09-27",
        "design": {
            "episode_ids": EPISODE_IDS,
            "policies": POLICIES,
            "proposal_latency_factors_ms": PROPOSAL_LATENCIES_MS,
            "default_command_latency_ms": DEFAULT_COMMAND_LATENCY_MS,
            "repetitions_per_cell": REPETITIONS,
            "action_start_boundary_rule": "proposal return + command latency; exogenous updates at the same tick are processed before action_start",
            "latency_source": "fixed test factors injected into DryRunClient; not API/model measurements",
        },
        "resources": {"model_api_calls": 0, "physical_devices_used": 0},
        "run_count": len(rows),
        "cell_count": len(groups),
        "deterministic_repeat_groups": deterministic_groups,
        "deterministic_repeat_group_count": len(groups),
        "rows": rows,
        "interpretation": (
            "Offline mechanism probe only. It tests whether state changes just before or during an action "
            "alter rejection, completion, safety, or goal metrics. It does not establish realistic latency, "
            "physical action rates, or a general coordination advantage."
        ),
    }


def main() -> None:
    result = run_probe()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT_PATH),
        "runs": result["run_count"],
        "cells": result["cell_count"],
        "deterministic_repeat_groups": result["deterministic_repeat_groups"],
        "model_api_calls": result["resources"]["model_api_calls"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
