"""Screen candidate tasks for a nontrivial safety/latency/service tradeoff.

This is a deterministic design audit, not a physical or human-validated result.
The paired controls change one declared variable in C2/C3 tasks and reuse the
same agent client, evaluator and architectures as the original episodes.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from evaluate import ROOT, evaluate, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.dry_run import DryRunClient
from runtime.execution import run_closed_loop_episode


ARCHITECTURES = (
    "CentralSingleAgent",
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
)
CONTROL_FAMILIES = {"indirect_environment_conflict", "resource_capacity_conflict"}


def safe_control(episode: dict) -> tuple[dict, dict] | None:
    """Build a single-variable no-conflict control for C2/C3 candidate tasks."""
    family = episode["task_family"]
    if family not in CONTROL_FAMILIES:
        return None
    altered = deepcopy(episode)
    altered["episode_id"] = f"{episode['episode_id']}.matched_safe"
    altered["base_episode_id"] = episode["episode_id"]

    if family == "indirect_environment_conflict":
        first, second = altered["task_stream"][:2]
        first_duration = next(
            item["duration_ms"]
            for item in altered["action_grounding"]
            if item["task_id"] == first["task_id"] and item["agent_id"] == first["agent_id"]
        )
        old_release = second["release_at_ms"]
        # The first dry-run action becomes effective at release + 700 ms.
        # A later second task guarantees no action overlap even after the
        # existing 300 ms synthetic central-agent latency difference.
        second["release_at_ms"] = first["release_at_ms"] + first_duration + 1000
        change = {
            "field": f"task_stream.{second['task_id']}.release_at_ms",
            "before": old_release,
            "after": second["release_at_ms"],
        }
    else:
        powers = [float(item["power_kw"]) for item in altered["action_grounding"]]
        safe_capacity = round(sum(powers) + 0.1, 6)
        old_capacity = altered["home"]["resources"]["max_power_kw"]
        altered["home"]["resources"]["max_power_kw"] = safe_capacity
        for rule in altered["conflict_rules"]:
            if rule["type"] == "C3":
                rule["capacity"] = safe_capacity
        change = {
            "field": "home.resources.max_power_kw and C3 rule capacity",
            "before": old_capacity,
            "after": safe_capacity,
        }
    return altered, change


def _compact(result: dict, trace: dict, release_at_ms: int) -> dict:
    action_ends = [
        item["timestamp_ms"] + item.get("duration_ms", 0) - release_at_ms
        for item in trace["events"] if item["type"] == "action_effective"
    ]
    return {
        "process_valid_success": result["process_valid_success"],
        "final_goal_success": result["final_goal_success"],
        "conflict_counts": result["conflict_counts"],
        "task_service_rate": result["task_service_rate"],
        "first_action_ms": result["first_effective_action_latency_ms"],
        "completion_ms": result["task_completion_time_ms"],
        "last_executed_action_end_ms": max(action_ends) if action_ends else None,
        "accepted_action_count": result["accepted_action_count"],
        "rejected_action_count": result["rejected_action_count"],
    }


def evaluate_case(episode: dict) -> dict[str, dict]:
    outcomes = {}
    for architecture in ARCHITECTURES:
        trace, result = run_closed_loop_episode(
            episode, DryRunClient(), architecture, INSTRUCTIONS, synthetic_latency=True
        )
        outcomes[architecture] = _compact(result, trace, episode["episode_release_at_ms"])
    return outcomes


def environment_only_goal_success(episode: dict) -> bool:
    """Can initial state and exogenous events satisfy the episode without agents?"""
    trace = {
        "trace_id": f"{episode['episode_id']}.environment_only",
        "episode_id": episode["episode_id"],
        "events": [
            {
                "type": "state_update",
                "timestamp_ms": item["at_ms"],
                "new_state_version": item["new_state_version"],
                "patch": item.get("patch", {}),
            }
            for item in episode.get("exogenous_events", [])
        ],
    }
    return bool(evaluate(episode, trace)["final_goal_success"])


def _nontrivial_safe_frontier(outcomes: dict[str, dict]) -> bool:
    """Ask whether safe baselines expose a strict service/latency tradeoff.

    A pair is nontrivial when neither is at least as good on task service,
    first physical action, and completion. Missing action time is not scored.
    """
    safe = [item for item in outcomes.values() if item["process_valid_success"]]
    for index, first in enumerate(safe):
        for second in safe[index + 1:]:
            fields = ("first_action_ms", "completion_ms")
            if any(first[field] is None or second[field] is None for field in fields):
                continue
            first_better = (
                first["task_service_rate"] > second["task_service_rate"]
                or any(first[field] < second[field] for field in fields)
            )
            second_better = (
                second["task_service_rate"] > first["task_service_rate"]
                or any(second[field] < first[field] for field in fields)
            )
            if first_better and second_better:
                return True
    return False


def run(output_path: Path) -> dict:
    cases = []
    for path in sorted((ROOT / "data" / "candidates").glob("*.json")):
        original = load_json(path)
        cases.append({
            "episode_id": original["episode_id"],
            "task_family": original["task_family"],
            "case_type": "candidate_original",
            "review_status": original.get("review_status"),
            "calibration_status": original.get("calibration", {}).get("status"),
            "change": None,
            "environment_only_goal_success": environment_only_goal_success(original),
            "outcomes": evaluate_case(original),
        })
        paired = safe_control(original)
        if paired:
            control, change = paired
            cases.append({
                "episode_id": control["episode_id"],
                "base_episode_id": original["episode_id"],
                "task_family": original["task_family"],
                "case_type": "matched_safe_control",
                "review_status": "generated_control_unreviewed",
                "calibration_status": original.get("calibration", {}).get("status"),
                "change": change,
                "environment_only_goal_success": environment_only_goal_success(control),
                "outcomes": evaluate_case(control),
            })

    originals = [case for case in cases if case["case_type"] == "candidate_original"]
    controls = [case for case in cases if case["case_type"] == "matched_safe_control"]
    strong = "ConstraintCoordinator"
    independent = "IndependentMultiAgent"
    central = "CentralSingleAgent"
    strong_valid = sum(case["outcomes"][strong]["process_valid_success"] for case in originals)
    central_valid = sum(case["outcomes"][central]["process_valid_success"] for case in originals)
    independent_valid = sum(case["outcomes"][independent]["process_valid_success"] for case in originals)
    strong_service_loss = sum(
        case["outcomes"][strong]["task_service_rate"] < case["outcomes"][independent]["task_service_rate"]
        for case in originals
    )
    strong_completion_slower = sum(
        case["outcomes"][strong]["completion_ms"] is not None
        and case["outcomes"][independent]["completion_ms"] is not None
        and case["outcomes"][strong]["completion_ms"] > case["outcomes"][independent]["completion_ms"]
        for case in originals
    )
    strong_first_slower = sum(
        case["outcomes"][strong]["first_action_ms"] is not None
        and case["outcomes"][independent]["first_action_ms"] is not None
        and case["outcomes"][strong]["first_action_ms"] > case["outcomes"][independent]["first_action_ms"]
        for case in originals
    )
    safe_frontier = sum(_nontrivial_safe_frontier(case["outcomes"]) for case in originals)
    control_valid = sum(case["outcomes"][independent]["process_valid_success"] for case in controls)
    control_overhead = sum(
        case["outcomes"][strong]["completion_ms"] != case["outcomes"][independent]["completion_ms"]
        or case["outcomes"][strong]["first_action_ms"] != case["outcomes"][independent]["first_action_ms"]
        or case["outcomes"][strong]["task_service_rate"] != case["outcomes"][independent]["task_service_rate"]
        for case in controls
    )
    environment_only = [case["episode_id"] for case in originals if case["environment_only_goal_success"]]
    missing_first_action = [
        case["episode_id"] for case in originals
        if case["outcomes"][strong]["first_action_ms"] is None
    ]

    payload = {
        "experiment": "candidate_tradeoff_design_audit",
        "status": "candidate_synthetic_deterministic_only",
        "definitions": {
            "strong_baseline": strong,
            "safe_frontier": "Two process-valid baselines each outperform the other on at least one of service rate, first action latency, and completion time; cases with missing latency are excluded.",
            "control_overhead": "Any difference in first action, completion, or service rate between the strong baseline and independent agents on a matched safe control.",
        },
        "summary": {
            "original_candidate_count": len(originals),
            "family_counts": dict(Counter(case["task_family"] for case in originals)),
            "matched_safe_control_count": len(controls),
            "strong_process_valid": strong_valid,
            "central_process_valid": central_valid,
            "independent_process_valid": independent_valid,
            "strong_service_loss_vs_independent": strong_service_loss,
            "strong_completion_slower_vs_independent": strong_completion_slower,
            "strong_first_action_slower_vs_independent": strong_first_slower,
            "originals_with_nontrivial_safe_frontier": safe_frontier,
            "controls_independent_process_valid": control_valid,
            "controls_with_strong_overhead": control_overhead,
            "originals_with_environment_only_goal_success": environment_only,
            "originals_with_no_strong_first_effective_action": missing_first_action,
        },
        "cases": cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "candidate_tradeoff_design_audit_20260924.json",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
