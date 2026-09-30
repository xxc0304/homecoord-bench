"""Deterministic sanity check of the four pilot conflict/control pairs."""

from __future__ import annotations

import json
from copy import deepcopy

from audit_candidate_tradeoffs import environment_only_goal_success
from evaluate import ROOT, validate_episode_shape
from make_paired_task_batch_v1 import build_batch
from run_protocol_pilot import INSTRUCTIONS
from runtime.dry_run import DryRunClient
from runtime.execution import run_closed_loop_episode
from runtime.protocol import build_agent_request


OUTPUT = ROOT / "results" / "paired_task_batch_v1_audit.json"


class ConditionalDryRunClient(DryRunClient):
    def decide(self, request: dict, instructions: str = "") -> dict:
        if (request["episode_id"].endswith("-CONTROL")
                and request["task"]["task_id"] in {"comfort_cool", "privacy_close"}):
            return {"response_type": "noop", "actions": [], "accepted_proposal_ids": [],
                    "rejected_proposal_ids": [], "defer_until_ms": None,
                    "reason_code": "no_applicable_action"}
        return super().decide(request, instructions)


def _local_request(episode: dict) -> dict:
    agent = episode["agents"][1]
    task = episode["task_stream"][1]
    request = build_agent_request(
        episode, agent, task, architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
    )
    for key in ("request_id", "episode_id", "base_episode_id"):
        request.pop(key, None)
    return request


def run() -> dict:
    episodes = build_batch()
    by_pair = {}
    for episode in episodes:
        by_pair.setdefault(episode["pair_id"], {})[episode["pair_condition"]] = episode
    rows = []
    for pair_id, conditions in by_pair.items():
        conflict, control = conditions["conflict"], conditions["control"]
        assert _local_request(conflict) == _local_request(control), pair_id
        for condition, episode in conditions.items():
            assert not validate_episode_shape(episode)
            assert not environment_only_goal_success(episode), episode["episode_id"]
            results = {}
            for architecture in ("IndependentMultiAgent", "ConstraintCoordinator"):
                trace, result = run_closed_loop_episode(
                    episode, ConditionalDryRunClient(), architecture, INSTRUCTIONS,
                    synthetic_latency=True,
                )
                results[architecture] = {
                    "process_valid_success": result["process_valid_success"],
                    "conflict_counts": result["conflict_counts"],
                    "task_service": result["task_service"],
                    "first_action_ms": result["first_effective_action_latency_ms"],
                    "goal_first_satisfied_ms": result["task_completion_time_ms"],
                    "accepted_action_count": result["accepted_action_count"],
                    "rejected_action_count": result["rejected_action_count"],
                }
            rows.append({"pair_id": pair_id, "condition": condition,
                         "episode_id": episode["episode_id"],
                         "local_agent_prompt_identical_across_pair": True,
                         "environment_only_goal_success": False,
                         "results": results})
    payload = {"status": "deterministic_design_check_not_model_or_device_result",
               "pairs": len(by_pair), "episodes": len(rows), "rows": rows}
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = run()
    for row in report["rows"]:
        independent = row["results"]["IndependentMultiAgent"]
        strong = row["results"]["ConstraintCoordinator"]
        print(json.dumps({"episode_id": row["episode_id"],
                          "independent_valid": independent["process_valid_success"],
                          "strong_valid": strong["process_valid_success"],
                          "independent_conflicts": independent["conflict_counts"],
                          "goal_delay_ms": None if independent["goal_first_satisfied_ms"] is None
                          or strong["goal_first_satisfied_ms"] is None else
                          strong["goal_first_satisfied_ms"] - independent["goal_first_satisfied_ms"]},
                         ensure_ascii=False))
