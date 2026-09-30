"""Run the deterministic event simulator across the current HomeCoord pilot corpus."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluate import ROOT, load_json
from runtime.dry_run import DryRunClient
from runtime.event_simulator import POLICY_DESCRIPTIONS, POLICIES, run_event_simulation


DATA_GROUPS = (
    "seeds",
    "pilot_pairs_v1",
    "pilot_physical_v2",
    "candidates",
)


def episode_paths(groups: tuple[str, ...] = DATA_GROUPS) -> list[tuple[str, Path]]:
    rows = []
    for group in groups:
        folder = ROOT / "data" / group
        if not folder.exists():
            continue
        rows.extend((group, path) for path in sorted(folder.glob("*.json"))
                    if path.name != "manifest.json")
    return rows


def compact_event_trace(trace: dict[str, Any]) -> dict[str, Any]:
    events = trace["events"]
    key_types = {
        "task_released", "proposal_returned", "coordination_decision",
        "action_started", "action_completed", "action_rejected", "state_update",
    }
    return {
        "event_count": len(events),
        "event_type_counts": dict(sorted(Counter(event["type"] for event in events).items())),
        "timeline": [
            {
                key: event[key]
                for key in (
                    "type", "timestamp_ms", "task_id", "agent_id", "decision", "reason",
                    "target", "operation", "latency_ms", "predicted_completion_at_ms",
                    "constraint_violation", "constraint_violation_started", "constraint_violation_resolved",
                )
                if key in event
            }
            for event in events if event["type"] in key_types
        ],
        "final_state": trace["final_state"],
        "final_state_version": trace["final_state_version"],
    }


def run_matrix(output_path: Path, groups: tuple[str, ...] = DATA_GROUPS) -> dict[str, Any]:
    policies = sorted(POLICIES)
    provider = DryRunClient()
    rows = []
    errors = []
    for group, path in episode_paths(groups):
        episode = load_json(path)
        for policy in policies:
            try:
                trace, result = run_event_simulation(episode, provider, policy, "")
                rows.append({
                    "group": group,
                    "episode_id": episode["episode_id"],
                    "policy": policy,
                    "metrics": {
                        key: result.get(key) for key in (
                            "final_goal_success", "process_valid_success", "task_service_rate",
                            "conflict_counts", "task_completion_time_ms", "task_action_finish_time_ms",
                            "first_action_start_latency_ms", "first_goal_progress_latency_ms",
                            "first_effective_action_latency_ms", "coordination_decision_latency_ms",
                            "task_deadline_met", "all_deadlines_met", "timely_process_valid_success",
                            "accepted_action_count", "rejected_action_count",
                            "completion_constraint_violation_count", "state_constraint_violation_episode_count",
                            "state_constraint_violation_duration_ms", "precondition_violations_at_start",
                        )
                    },
                    "trace": compact_event_trace(trace),
                })
            except Exception as exc:  # keep a failed case visible in the batch report
                errors.append({
                    "group": group, "episode_id": episode.get("episode_id", path.stem),
                    "policy": policy, "error_type": type(exc).__name__, "error": str(exc),
                })

    summary = {
        "schema_version": "event-simulation-matrix-0.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "deterministic_dry_run",
        "latency_semantics": "proposal returns are placed on a virtual clock; model calls are not concurrent",
        "execution_semantics": "start effects apply at action_started; completion effects apply at action_completed",
        "device_calibration": "not_device_calibrated; synthetic and candidate parameters remain assumptions",
        "groups": list(groups),
        "policies": policies,
        "policy_descriptions": {policy: POLICY_DESCRIPTIONS[policy] for policy in policies},
        "episode_count": len({row["episode_id"] for row in rows}),
        "run_count": len(rows),
        "error_count": len(errors),
        "rows": rows,
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "event_simulation_matrix_20260926.json",
    )
    parser.add_argument("--groups", nargs="+", choices=DATA_GROUPS, default=list(DATA_GROUPS))
    args = parser.parse_args()
    report = run_matrix(args.output, tuple(args.groups))
    print(json.dumps({
        "output": str(args.output),
        "episodes": report["episode_count"],
        "runs": report["run_count"],
        "errors": report["error_count"],
        "policies": report["policies"],
    }, ensure_ascii=False, indent=2))
