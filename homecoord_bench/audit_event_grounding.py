"""Audit action grounding, effect phases, and event-episode coverage."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluate import ROOT, load_json
from runtime.dry_run import DryRunClient
from runtime.protocol import build_agent_request


GROUPS = ("seeds", "pilot_pairs_v1", "pilot_physical_v2", "candidates")
ACTIVE_LIKE_VALUES = {
    "active", "on", "high", "running", "heating", "charging", "opening",
    "closing", "washing", "drying", "arming",
}


def _paths(group: str) -> list[Path]:
    folder = ROOT / "data" / group
    return sorted(path for path in folder.glob("*.json") if path.name != "manifest.json")


def audit() -> dict[str, Any]:
    by_group = {}
    provider = DryRunClient()
    for group in GROUPS:
        episode_rows = []
        grounding_count = explicit_count = long_count = long_explicit = 0
        task_count = proposal_count = grounded_proposal_count = 0
        completion_deadline_task_count = 0
        active_like_unphased = []
        ungrounded_proposals = []
        for path in _paths(group):
            episode = load_json(path)
            agents = {agent["agent_id"]: agent for agent in episode["agents"]}
            action_rows = []
            for action in episode.get("action_grounding", []):
                grounding_count += 1
                duration_ms = int(action.get("duration_ms", 0))
                explicit = "start_effects" in action and "completion_effects" in action
                explicit_count += int(explicit)
                is_long = duration_ms >= 1000
                long_count += int(is_long)
                long_explicit += int(is_long and explicit)
                active_values = sorted({
                    value for patch_name in ("effects", "start_effects", "completion_effects")
                    for value in action.get(patch_name, {}).values()
                    if isinstance(value, str) and value.lower() in ACTIVE_LIKE_VALUES
                })
                if is_long and active_values and not explicit:
                    active_like_unphased.append({
                        "episode_id": episode["episode_id"],
                        "task_id": action.get("task_id"),
                        "operation": action.get("operation"),
                        "duration_ms": duration_ms,
                        "active_like_values": active_values,
                    })
                action_rows.append({
                    "task_id": action.get("task_id"),
                    "operation": action.get("operation"),
                    "duration_ms": duration_ms,
                    "explicit_effect_phases": explicit,
                    "active_like_values": active_values,
                })
            for task in episode["task_stream"]:
                task_count += 1
                completion_deadline_task_count += int(
                    task.get("completion_deadline_ms") is not None
                )
                request = build_agent_request(
                    episode,
                    agents[task["agent_id"]],
                    task,
                    architecture="IndependentMultiAgent",
                    current_time_ms=task["release_at_ms"],
                    current_state=episode["initial_state"]["values"],
                    state_version=episode["initial_state"]["version"],
                    include_evaluation_hints=True,
                )
                decision = provider.decide(request)
                for proposed_action in decision.get("actions", []):
                    proposal_count += 1
                    covered = any(
                        grounding.get("agent_id") == task["agent_id"]
                        and grounding.get("task_id") == task["task_id"]
                        and grounding.get("operation", "*") in {"*", proposed_action["operation"]}
                        for grounding in episode.get("action_grounding", [])
                    )
                    grounded_proposal_count += int(covered)
                    if not covered:
                        ungrounded_proposals.append({
                            "episode_id": episode["episode_id"],
                            "task_id": task["task_id"],
                            "agent_id": task["agent_id"],
                            "operation": proposed_action["operation"],
                        })
            episode_rows.append({
                "episode_id": episode["episode_id"],
                "exogenous_event_count": len(episode.get("exogenous_events", [])),
                "grounding_count": len(action_rows),
                "actions": action_rows,
            })
        by_group[group] = {
            "episode_count": len(episode_rows),
            "grounding_count": grounding_count,
            "explicit_phase_count": explicit_count,
            "long_action_count_ge_1000ms": long_count,
            "long_action_explicit_phase_count": long_explicit,
            "active_like_unphased_count": len(active_like_unphased),
            "active_like_unphased": active_like_unphased,
            "task_count": task_count,
            "completion_deadline_task_count": completion_deadline_task_count,
            "dry_run_proposal_count": proposal_count,
            "grounded_dry_run_proposal_count": grounded_proposal_count,
            "ungrounded_dry_run_proposal_count": proposal_count - grounded_proposal_count,
            "ungrounded_dry_run_proposals": ungrounded_proposals,
            "episodes": episode_rows,
        }
    totals = {
        "episode_count": sum(item["episode_count"] for item in by_group.values()),
        "task_count": sum(item["task_count"] for item in by_group.values()),
        "completion_deadline_task_count": sum(
            item["completion_deadline_task_count"] for item in by_group.values()
        ),
        "grounding_count": sum(item["grounding_count"] for item in by_group.values()),
        "long_action_count_ge_1000ms": sum(
            item["long_action_count_ge_1000ms"] for item in by_group.values()
        ),
        "long_action_explicit_phase_count": sum(
            item["long_action_explicit_phase_count"] for item in by_group.values()
        ),
        "active_like_unphased_count": sum(
            item["active_like_unphased_count"] for item in by_group.values()
        ),
        "dry_run_proposal_count": sum(
            item["dry_run_proposal_count"] for item in by_group.values()
        ),
        "grounded_dry_run_proposal_count": sum(
            item["grounded_dry_run_proposal_count"] for item in by_group.values()
        ),
        "ungrounded_dry_run_proposal_count": sum(
            item["ungrounded_dry_run_proposal_count"] for item in by_group.values()
        ),
        "episode_with_exogenous_events_count": sum(
            row["exogenous_event_count"] > 0
            for item in by_group.values()
            for row in item["episodes"]
        ),
        "exogenous_event_count": sum(
            row["exogenous_event_count"]
            for item in by_group.values()
            for row in item["episodes"]
        ),
    }
    totals["long_action_missing_explicit_phase_count"] = (
        totals["long_action_count_ge_1000ms"]
        - totals["long_action_explicit_phase_count"]
    )
    return {
        "schema_version": "event-grounding-audit-0.2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "groups": by_group,
        "totals": totals,
        "interpretation": (
            "Audit checks dry-run operation coverage and flags missing temporal annotations "
            "or active-like status strings. It does not establish that a device physically "
            "exposes an intermediate state or that any assumed parameter is calibrated."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "event_grounding_audit_20260926.json",
    )
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "totals": report["totals"],
        "groups": {
            key: {
                name: value[name] for name in (
                    "episode_count", "grounding_count", "explicit_phase_count",
                    "long_action_count_ge_1000ms", "long_action_explicit_phase_count",
                    "active_like_unphased_count", "task_count", "dry_run_proposal_count",
                    "grounded_dry_run_proposal_count", "ungrounded_dry_run_proposal_count",
                )
            }
            for key, value in report["groups"].items()
        },
    }, ensure_ascii=False, indent=2))
