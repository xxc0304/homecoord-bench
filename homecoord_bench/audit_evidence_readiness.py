"""Read-only quality gate for candidate benchmark episodes.

This does not replace human review. It flags known reasons that a candidate
cannot yet support a physical or generalizable conflict/latency claim.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from audit_candidate_tradeoffs import environment_only_goal_success
from evaluate import ROOT, load_json


OUTPUT = ROOT / "results" / "evidence_readiness_audit_20260926.json"


def audit_episode(episode: dict) -> dict:
    flags = []
    if environment_only_goal_success(episode):
        flags.append("goal_satisfied_without_any_agent")
    if any(item.get("environment_effects") for item in episode.get("action_grounding", [])):
        flags.append("environment_effects_not_applied_by_runtime")
    if not any(task.get("completion_deadline_ms") is not None for task in episode["task_stream"]):
        flags.append("no_task_deadline_for_urgency_analysis")
    if episode.get("review_status") not in {"double_reviewed", "adjudicated"}:
        flags.append("task_not_double_reviewed")
    if episode.get("calibration", {}).get("status") == "synthetic_range":
        flags.append("device_timing_and_power_synthetic")
    if not episode.get("tool_catalog"):
        flags.append("callable_action_signatures_not_specified")
    return {"episode_id": episode["episode_id"], "family": episode["task_family"], "flags": flags}


def run(output: Path = OUTPUT) -> dict:
    rows = [audit_episode(load_json(path)) for path in sorted((ROOT / "data" / "candidates").glob("*.json"))]
    payload = {
        "experiment": "evidence_readiness_audit",
        "status": "automatic_flags_only_not_human_review",
        "candidate_count": len(rows),
        "flag_counts": dict(Counter(flag for row in rows for flag in row["flags"])),
        "rows": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run()["flag_counts"], ensure_ascii=False, indent=2))
