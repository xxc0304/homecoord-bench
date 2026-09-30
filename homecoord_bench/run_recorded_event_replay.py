"""Replay saved DeepSeek proposals and measured latencies in the event simulator.

This script makes no network calls. It compares online execution policies on
fixed proposal records; it does not re-sample model behavior per architecture.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluate import ROOT, load_json
from probe_blind_capacity_pair_20260926 import make_episode as make_blind_capacity_episode
from runtime.event_simulator import POLICY_DESCRIPTIONS, run_event_simulation
from runtime.replay_client import MemoryReplayClient


POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
)
PAIR_RESULT = ROOT / "results" / "paired_task_batch_v1_probe.json"
BLIND_RESULT = ROOT / "results" / "blind_capacity_pair_20260926.json"
PHYSICAL_RESULT = ROOT / "results" / "physical_capacity_v2.json"


def _compact_trace(trace: dict[str, Any]) -> dict[str, Any]:
    events = trace["events"]
    keep = (
        "type", "timestamp_ms", "task_id", "agent_id", "decision", "reason",
        "target", "operation", "latency_ms", "defer_until_ms",
        "constraint_violation_started", "constraint_violation_resolved", "constraint_violation",
    )
    return {
        "event_type_counts": dict(sorted(Counter(event["type"] for event in events).items())),
        "timeline": [{key: event[key] for key in keep if key in event} for event in events],
    }


def _replay_one(episode: dict[str, Any], records: list[dict[str, Any]], policy: str) -> dict[str, Any]:
    replay = MemoryReplayClient(records)
    trace, result = run_event_simulation(episode, replay, policy, "")
    replay.assert_consumed()
    return {
        "episode_id": episode["episode_id"],
        "policy": policy,
        "metrics": {
            key: result.get(key) for key in (
                "final_goal_success", "process_valid_success", "task_service_rate", "task_service",
                "conflict_counts", "task_completion_time_ms", "task_action_finish_time_ms",
                "task_deadline_met", "all_deadlines_met", "timely_process_valid_success",
                "first_action_start_latency_ms", "first_goal_progress_latency_ms",
                "first_effective_action_latency_ms",
                "coordination_decision_latency_ms", "accepted_action_count", "rejected_action_count",
                "completion_constraint_violation_count", "state_constraint_violation_episode_count",
                "state_constraint_violation_duration_ms",
            )
        },
        "trace": _compact_trace(trace),
    }


def _records(*items: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"decision": item["decision"], "logical_latency_ms": item["logical_latency_ms"]}
            for item in items]


def _run_paired_task_rows() -> list[dict[str, Any]]:
    source = load_json(PAIR_RESULT)
    episodes_by_pair: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted((ROOT / "data" / "pilot_pairs_v1").glob("HC-PAIR-*.json")):
        episode = load_json(path)
        episodes_by_pair.setdefault(episode["pair_id"], {})[episode["pair_condition"]] = episode

    rows = []
    for sample in source["rows"]:
        records = sample.get("model_records", {})
        if "conditions" not in sample or not {"first_conflict", "first_control", "shared_local"}.issubset(records):
            continue
        pair_id = sample["pair_id"]
        for condition, first_key in (("conflict", "first_conflict"), ("control", "first_control")):
            episode = episodes_by_pair[pair_id][condition]
            model_records = _records(records[first_key], records["shared_local"])
            for policy in POLICIES:
                rows.append({
                    "source": "paired_task_batch_v1_probe.json",
                    "pair_id": pair_id,
                    "condition": condition,
                    "repetition": sample["repetition"],
                    **_replay_one(episode, model_records, policy),
                })
    return rows


def _run_blind_capacity_rows() -> list[dict[str, Any]]:
    source = load_json(BLIND_RESULT)
    episodes = {"low": make_blind_capacity_episode(1.2), "high": make_blind_capacity_episode(1.6)}
    rows = []
    for sample in source["rows"]:
        records = sample.get("model_records")
        if "outcomes" not in sample or not isinstance(records, list) or len(records) != 2:
            continue
        replay_records = _records(*records)
        for condition, episode in episodes.items():
            for policy in POLICIES:
                rows.append({
                    "source": "blind_capacity_pair_20260926.json",
                    "pair_id": "C3-LIGHT-HVAC",
                    "condition": condition,
                    "repetition": sample["repetition"],
                    **_replay_one(episode, replay_records, policy),
                })
    return rows


def _run_physical_capacity_rows() -> list[dict[str, Any]]:
    source = load_json(PHYSICAL_RESULT)
    episodes = {
        condition: load_json(ROOT / "data" / "pilot_physical_v2" / f"{condition}.json")
        for condition in ("conflict", "control")
    }
    rows = []
    for sample in source["rows"]:
        records = sample.get("model_records", {})
        if "outcomes" not in sample or not {"charge_ev", "heat_water"}.issubset(records):
            continue
        replay_records = _records(records["charge_ev"], records["heat_water"])
        for condition, episode in episodes.items():
            for policy in POLICIES:
                rows.append({
                    "source": "physical_capacity_v2.json",
                    "pair_id": "C3-EV-WATER-PHYSICAL",
                    "condition": condition,
                    "repetition": sample["repetition"],
                    **_replay_one(episode, replay_records, policy),
                })
    return rows


def run(output_path: Path) -> dict[str, Any]:
    rows = _run_paired_task_rows() + _run_blind_capacity_rows() + _run_physical_capacity_rows()
    report = {
        "schema_version": "recorded-event-replay-0.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "offline_replay_of_saved_deepseek_proposals",
        "network_calls": 0,
        "api_calls_concurrent": False,
        "proposal_semantics": "each condition reuses its recorded model decision and measured call latency",
        "policy_scope": list(POLICIES),
        "policy_descriptions": {policy: POLICY_DESCRIPTIONS[policy] for policy in POLICIES},
        "excluded_architecture_reason": "CentralSingleAgent needs its own central-agent proposals; specialist outputs would be an unfair substitution",
        "device_calibration": "synthetic_or_unreviewed_assumptions",
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
        default=ROOT / "results" / "recorded_event_replay_20260926.json",
    )
    args = parser.parse_args()
    report = run(args.output)
    summary = {
        "output": str(args.output), "runs": report["run_count"],
        "network_calls": report["network_calls"], "policies": report["policy_scope"],
        "sources": dict(sorted(Counter(row["source"] for row in report["rows"]).items())),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
