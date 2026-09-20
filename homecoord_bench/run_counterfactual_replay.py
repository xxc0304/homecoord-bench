"""Apply one architecture to another architecture's identical proposals and latencies."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from evaluate import evaluate, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.execution import run_closed_loop_episode
from runtime.replay_client import MemoryReplayClient


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def latency_delta(counterfactual: int | None, source: int | None) -> int | None:
    if counterfactual is None or source is None:
        return None
    delta = counterfactual - source
    return 0 if abs(delta) <= 1 else delta


def run(run_dir: Path, output: Path, family: str, target_architecture: str) -> dict:
    episodes = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
    episode_by_id = {episode["episode_id"]: episode for episode in episodes}
    raw_rows = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (run_dir / "model_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    starts = {}
    terminals: dict[str, list[dict]] = defaultdict(list)
    completed_order = []
    for event in events:
        request_id = event.get("request_id")
        if event["event_type"] == "model_call_started" and event.get("attempt") == 1:
            starts[request_id] = event
        elif event["event_type"] in {"model_call_failed", "model_call_completed"}:
            terminals[request_id].append(event)
            if event["event_type"] == "model_call_completed":
                completed_order.append(event)

    pairs = []
    for raw in raw_rows:
        if raw.get("architecture") != "IndependentMultiAgent" or raw.get("family") != family:
            continue
        episode_id = raw["episode_id"]
        episode = episode_by_id[episode_id]
        records = []
        for completed in completed_order:
            request_id = completed["request_id"]
            started = starts.get(request_id, {})
            if started.get("episode_id") != episode_id or started.get("architecture") != "IndependentMultiAgent":
                continue
            records.append({
                "decision": completed["decision"],
                "logical_latency_ms": sum(float(item.get("latency_ms") or 0) for item in terminals[request_id]),
            })
        replay = MemoryReplayClient(records)
        counterfactual_trace, counterfactual = run_closed_loop_episode(
            episode,
            replay,
            target_architecture,
            INSTRUCTIONS,
            synthetic_latency=False,
        )
        replay.assert_consumed()
        source_trace = load_json(run_dir / f"{raw['trace_id']}.json")
        source = evaluate(episode, source_trace)
        pairs.append({
            "episode_id": episode_id,
            "base_variant_id": raw.get("base_variant_id", episode_id.split(".rep-", 1)[0]),
            "repetition": raw.get("repetition", 1),
            "source_independent": source,
            "counterfactual": counterfactual,
            "delta_first_action_ms": latency_delta(
                counterfactual["first_effective_action_latency_ms"], source["first_effective_action_latency_ms"]
            ),
            "delta_completion_ms": latency_delta(
                counterfactual["task_completion_time_ms"], source["task_completion_time_ms"]
            ),
            "counterfactual_trace": counterfactual_trace,
        })

    first_deltas = [pair["delta_first_action_ms"] for pair in pairs if pair["delta_first_action_ms"] is not None]
    completion_deltas = [pair["delta_completion_ms"] for pair in pairs if pair["delta_completion_ms"] is not None]
    conflicted_pairs = [pair for pair in pairs if sum(pair["source_independent"]["conflict_counts"].values()) > 0]
    safe_pairs = [pair for pair in pairs if sum(pair["source_independent"]["conflict_counts"].values()) == 0]

    def delta_summary(selected: list[dict], field: str) -> dict:
        values = [pair[field] for pair in selected if pair[field] is not None]
        return {
            "pairs": len(selected),
            "p50": median(values) if values else None,
            "p95": percentile(values, 0.95),
        }

    report = {
        "status": "counterfactual replay on identical specialist decisions and logical call latencies",
        "source_run": str(run_dir),
        "family": family,
        "source_architecture": "IndependentMultiAgent",
        "target_architecture": target_architecture,
        "pairs": len(pairs),
        "source_process_valid_successes": sum(pair["source_independent"]["process_valid_success"] for pair in pairs),
        "counterfactual_process_valid_successes": sum(pair["counterfactual"]["process_valid_success"] for pair in pairs),
        "source_conflict_episodes": {
            key: sum(pair["source_independent"]["conflict_counts"][key] > 0 for pair in pairs)
            for key in ("C1", "C2", "C3", "C4")
        },
        "counterfactual_conflict_episodes": {
            key: sum(pair["counterfactual"]["conflict_counts"][key] > 0 for pair in pairs)
            for key in ("C1", "C2", "C3", "C4")
        },
        "source_mean_task_service_rate": mean(pair["source_independent"]["task_service_rate"] for pair in pairs),
        "counterfactual_mean_task_service_rate": mean(pair["counterfactual"]["task_service_rate"] for pair in pairs),
        "delta_first_action_ms": {
            "p50": median(first_deltas) if first_deltas else None,
            "p95": percentile(first_deltas, 0.95),
        },
        "delta_completion_ms": {
            "p50": median(completion_deltas) if completion_deltas else None,
            "p95": percentile(completion_deltas, 0.95),
        },
        "source_conflicted_pairs_delta_completion_ms": delta_summary(conflicted_pairs, "delta_completion_ms"),
        "source_safe_pairs_delta_completion_ms": delta_summary(safe_pairs, "delta_completion_ms"),
        "results": pairs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--family",
        choices=("direct_device_conflict", "indirect_environment_conflict", "resource_capacity_conflict"),
        default="direct_device_conflict",
    )
    parser.add_argument(
        "--target-architecture",
        choices=("RuleCoordinator", "ConstraintCoordinator"),
        default="RuleCoordinator",
    )
    args = parser.parse_args()
    result = run(args.run_dir, args.output, args.family, args.target_architecture)
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False, indent=2))
