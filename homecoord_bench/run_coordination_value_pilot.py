"""Small paired LLM pilot for the value and overhead of strong coordination.

This is an unreviewed candidate-data pilot, not a benchmark result. The strong
coordinator replays exactly the independent agents' decisions and logical API
latencies. Its local rule-check time is not part of the simulator clock.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from time import perf_counter_ns

from audit_candidate_tradeoffs import safe_control
from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.execution import run_closed_loop_episode
from runtime.replay_client import MemoryReplayClient


SELECTED = ("HC-M06", "HC-M07", "HC-M08", "HC-M11", "HC-M12", "HC-M13")
RUN_DIR = ROOT / "runs" / "coordination_value_pilot_20260926"
OUTPUT = ROOT / "results" / "coordination_value_pilot_20260926.json"


class RecordingClient:
    def __init__(self, underlying: DeepSeekResponsesClient):
        self.underlying = underlying
        self.records: list[dict] = []
        self.last_latency_ms = 0

    def decide(self, request: dict, instructions: str = "") -> dict:
        start = perf_counter_ns()
        decision = self.underlying.decide(request, instructions)
        self.last_latency_ms = max(1, round((perf_counter_ns() - start) / 1_000_000))
        self.records.append({
            "decision": deepcopy(decision),
            "logical_latency_ms": self.last_latency_ms,
            "task_id": request["task"]["task_id"],
        })
        return decision


def physical_end(trace: dict, release: int) -> int | None:
    ends = [
        event["timestamp_ms"] + event.get("duration_ms", 0) - release
        for event in trace["events"] if event["type"] == "action_effective"
    ]
    return max(ends) if ends else None


def metrics(trace: dict, result: dict, release: int) -> dict:
    return {
        "process_valid_success": result["process_valid_success"],
        "conflict_counts": result["conflict_counts"],
        "task_service_rate": result["task_service_rate"],
        "first_action_ms": result["first_effective_action_latency_ms"],
        "goal_first_satisfied_ms": result["task_completion_time_ms"],
        "last_action_end_ms": physical_end(trace, release),
        "accepted_action_count": result["accepted_action_count"],
        "rejected_action_count": result["rejected_action_count"],
    }


def difference(strong: dict, independent: dict, name: str) -> int | float | None:
    a, b = strong[name], independent[name]
    return None if a is None or b is None else a - b


def run() -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "coordination-value-pilot")
    model = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    rows = []

    for episode_id in SELECTED:
        original = load_json(ROOT / "data" / "candidates" / f"{episode_id}.json")
        matched = safe_control(original)
        if matched is None:
            raise ValueError(f"no matched safe control for {episode_id}")
        for condition, episode in (("original", original), ("matched_safe", matched[0])):
            recorder = RecordingClient(model)
            try:
                source_trace, source_result = run_closed_loop_episode(
                    episode, recorder, "IndependentMultiAgent", INSTRUCTIONS,
                    synthetic_latency=False,
                )
                replay = MemoryReplayClient(recorder.records)
                strong_trace, strong_result = run_closed_loop_episode(
                    episode, replay, "ConstraintCoordinator", INSTRUCTIONS,
                    synthetic_latency=False,
                )
                replay.assert_consumed()
                release = episode["episode_release_at_ms"]
                independent = metrics(source_trace, source_result, release)
                strong = metrics(strong_trace, strong_result, release)
                row = {
                    "episode_id": episode["episode_id"],
                    "base_episode_id": episode_id,
                    "family": original["task_family"],
                    "condition": condition,
                    "model_call_latencies_ms": [record["logical_latency_ms"] for record in recorder.records],
                    "proposal_action_counts": [len(record["decision"].get("actions", [])) for record in recorder.records],
                    "independent": independent,
                    "strong_same_proposals": strong,
                    "delta_first_action_ms": difference(strong, independent, "first_action_ms"),
                    "delta_goal_first_satisfied_ms": difference(strong, independent, "goal_first_satisfied_ms"),
                    "delta_last_action_end_ms": difference(strong, independent, "last_action_end_ms"),
                    "delta_task_service_rate": difference(strong, independent, "task_service_rate"),
                }
                (RUN_DIR / f"{episode['episode_id']}.independent.json").write_text(
                    json.dumps(source_trace, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (RUN_DIR / f"{episode['episode_id']}.strong.json").write_text(
                    json.dumps(strong_trace, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as exc:
                row = {
                    "episode_id": episode["episode_id"],
                    "base_episode_id": episode_id,
                    "family": original["task_family"],
                    "condition": condition,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in (
                "episode_id", "condition", "proposal_action_counts", "delta_first_action_ms",
                "delta_goal_first_satisfied_ms", "delta_last_action_end_ms",
                "delta_task_service_rate", "error_type"
            )}, ensure_ascii=False), flush=True)
            OUTPUT.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    completed = [row for row in rows if "error_type" not in row]
    controls = [row for row in completed if row["condition"] == "matched_safe"]
    valid_controls = [row for row in controls if row["independent"]["process_valid_success"]]
    summary = {
        "selected_pairs": len(SELECTED),
        "completed_cases": len(completed),
        "errors": len(rows) - len(completed),
        "safe_controls_completed": len(controls),
        "safe_controls_independent_process_valid": len(valid_controls),
        "safe_controls_with_any_strong_penalty": sum(
            any(row[key] is not None and row[key] > 0 for key in (
                "delta_first_action_ms", "delta_goal_first_satisfied_ms", "delta_last_action_end_ms"
            )) or row["delta_task_service_rate"] < 0
            for row in valid_controls
        ),
        "safe_control_goal_latency_delta_median_ms": median(
            row["delta_goal_first_satisfied_ms"] for row in valid_controls
            if row["delta_goal_first_satisfied_ms"] is not None
        ) if valid_controls else None,
    }
    report = {
        "experiment": "coordination_value_pilot",
        "status": "unreviewed_candidate_pilot_real_llm_proposals_synthetic_devices",
        "model": "deepseek-flash",
        "comparison": "IndependentMultiAgent versus ConstraintCoordinator on identical decisions and measured logical API latencies",
        "limits": [
            "Candidate tasks and generated controls lack human double review and device calibration.",
            "One API draw per condition; no population-level confidence interval.",
            "The replay holds model proposals fixed and does not measure proposal adaptation in a coordinator-aware closed loop.",
            "Simulator coordination checks consume zero virtual time; real state synchronization, networking and device feedback are not measured.",
            "Last action end is the end of the final accepted action, not a proof that the household goal persisted.",
        ],
        "summary": summary,
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run()["summary"], ensure_ascii=False, indent=2))
