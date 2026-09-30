"""Summarize which coordination baselines are actually covered by each pilot."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUTPUT = RESULTS / "baseline_coverage_audit_20260926.json"


def _load(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def _policy_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(row.get("policy", "<missing>") for row in rows).items()))


def audit() -> dict[str, Any]:
    matrix = _load("event_simulation_matrix_20260926.json")
    replay = _load("recorded_event_replay_20260926.json")
    deadline = _load("event_deadline_sensitivity_20260926.json")
    online = _load("recorded_online_policies_v1.json")

    matrix_rows = matrix.get("rows", [])
    matrix_by_group: dict[str, Counter[str]] = defaultdict(Counter)
    for row in matrix_rows:
        matrix_by_group[row.get("group", "<missing>")][row.get("policy", "<missing>")] += 1

    replay_rows = replay.get("rows", [])
    deadline_rows = deadline.get("rows", [])
    online_rows = online.get("rows", [])
    deadline_values = sorted({row.get("ev_deadline_ms") for row in deadline_rows
                              if row.get("ev_deadline_ms") is not None})
    online_conditions = sorted({row.get("condition") for row in online_rows})
    overhead_values = [
        row.get("metrics", {}).get("coordination_decision_latency_ms")
        for row in matrix_rows
    ]
    overhead_measured = sum(isinstance(value, (int, float)) for value in overhead_values)

    replay_policies = set(_policy_counts(replay_rows))
    matrix_policies = set(_policy_counts(matrix_rows))
    return {
        "schema_version": "baseline-coverage-audit-0.1",
        "status": "partial_coverage_strong_rules_present_with_model_architecture_gap",
        "event_matrix": {
            "run_count": matrix.get("run_count", len(matrix_rows)),
            "episode_count": matrix.get("episode_count"),
            "policies": sorted(matrix_policies),
            "policy_run_counts": _policy_counts(matrix_rows),
            "group_policy_run_counts": {
                group: dict(sorted(counts.items()))
                for group, counts in sorted(matrix_by_group.items())
            },
            "proposal_source": matrix.get("provider"),
        },
        "recorded_model_proposal_replay": {
            "run_count": replay.get("run_count", len(replay_rows)),
            "policies": sorted(replay_policies),
            "policy_run_counts": _policy_counts(replay_rows),
            "network_calls": replay.get("network_calls"),
            "api_calls_concurrent": replay.get("api_calls_concurrent"),
            "central_agent_excluded": "CentralSingleAgent" not in replay_policies,
            "central_agent_exclusion_reason": replay.get("excluded_architecture_reason"),
            "scope": replay.get("policy_scope"),
        },
        "deadline_sensitivity_replay": {
            "run_count": deadline.get("run_count", len(deadline_rows)),
            "policies": sorted(_policy_counts(deadline_rows)),
            "policy_run_counts": _policy_counts(deadline_rows),
            "distinct_deadline_values_ms": deadline_values,
            "network_calls": deadline.get("network_calls"),
        },
        "direct_online_rule_replay": {
            "run_count": len(online_rows),
            "conditions": online_conditions,
            "policies": sorted(_policy_counts(online_rows)),
            "policy_run_counts": _policy_counts(online_rows),
            "source_status": online.get("status"),
        },
        "coordination_overhead": {
            "event_matrix_runs": len(matrix_rows),
            "runs_with_numeric_decision_latency": overhead_measured,
            "status": "not_measured_in_current_event_matrix" if not overhead_measured else "partially_measured",
        },
        "gaps": [
            "CentralSingleAgent is present in the scripted event matrix but excluded from the saved specialist-proposal replay; a fair model comparison needs its own central-agent proposals and equal budgets.",
            "Saved DeepSeek calls were collected sequentially and their latencies replayed on a logical clock; this is not concurrent API execution.",
            "Local coordination computation, state-read/network synchronization, device acknowledgement, and feedback costs are not timed in the current event matrix.",
            "The available deadline tasks are one EV/water template under conflict/control conditions, not broad deadline coverage.",
        ],
        "interpretation": (
            "The pilots already include meaningful deterministic and deadline-aware rules, "
            "so a weak no-coordination baseline is not the only comparator. Coverage is "
            "still incomplete for fair model-based architecture comparisons and real "
            "coordination overhead."
        ),
    }


if __name__ == "__main__":
    payload = audit()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "event_matrix_runs": payload["event_matrix"]["run_count"],
        "event_matrix_policies": payload["event_matrix"]["policies"],
        "model_replay_runs": payload["recorded_model_proposal_replay"]["run_count"],
        "model_replay_policies": payload["recorded_model_proposal_replay"]["policies"],
        "deadline_sensitivity_runs": payload["deadline_sensitivity_replay"]["run_count"],
        "direct_online_rule_runs": payload["direct_online_rule_replay"]["run_count"],
        "coordination_overhead": payload["coordination_overhead"],
        "output": str(OUTPUT),
    }, ensure_ascii=False, indent=2))
