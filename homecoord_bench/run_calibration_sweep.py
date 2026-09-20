"""Run deterministic sensitivity sweeps over synthetic action ranges."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.calibration import calibration_manifest, parameterize_episode
from runtime.dry_run import DryRunClient
from runtime.execution import run_closed_loop_episode


ARCHITECTURES = ["CentralSingleAgent", "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator"]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, round((len(values) - 1) * fraction))
    return values[index]


def run(replicates: int, output_path: Path) -> dict:
    rows = []
    manifests = []
    for path in sorted((ROOT / "data" / "candidates").glob("*.json")):
        episode = load_json(path)
        manifests.append(calibration_manifest(episode))
        for replicate in range(1, replicates + 1):
            sampled = parameterize_episode(episode, replicate)
            for architecture in ARCHITECTURES:
                trace, result = run_closed_loop_episode(
                    sampled, DryRunClient(), architecture, INSTRUCTIONS, synthetic_latency=True
                )
                rows.append({
                    "episode_id": episode["episode_id"],
                    "task_family": episode["task_family"],
                    "architecture": architecture,
                    "replicate": replicate,
                    "process_valid_success": result["process_valid_success"],
                    "final_goal_success": result["final_goal_success"],
                    "conflict_counts": result["conflict_counts"],
                    "task_service_rate": result["task_service_rate"],
                    "completion_ms": result["task_completion_time_ms"],
                    "first_action_ms": result["first_effective_action_latency_ms"],
                })

    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["task_family"], row["architecture"])].append(row)
    aggregate = []
    for (family, architecture), items in sorted(grouped.items()):
        completion = [item["completion_ms"] for item in items if item["completion_ms"] is not None]
        conflicts = defaultdict(int)
        for item in items:
            for key, value in item["conflict_counts"].items():
                conflicts[key] += value
        aggregate.append({
            "task_family": family,
            "architecture": architecture,
            "runs": len(items),
            "process_valid_rate": sum(item["process_valid_success"] for item in items) / len(items),
            "final_goal_rate": sum(item["final_goal_success"] for item in items) / len(items),
            "mean_task_service_rate": sum(item["task_service_rate"] for item in items) / len(items),
            "conflict_counts": dict(conflicts),
            "completion_p50_ms": median(completion) if completion else None,
            "completion_p95_ms": _percentile(completion, 0.95),
        })

    payload = {
        "experiment": "synthetic_calibration_sweep",
        "status": "sensitivity_only",
        "replicates_per_episode": replicates,
        "episodes": len(manifests),
        "architectures": ARCHITECTURES,
        "parameter_policy": {
            "duration_relative_range": [0.80, 1.20],
            "power_relative_range": [0.85, 1.15],
            "event_jitter_ms": 0,
            "physical_claims_allowed": False,
        },
        "manifests": manifests,
        "aggregate": aggregate,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "synthetic_calibration_sweep_20260920.json")
    args = parser.parse_args()
    payload = run(args.replicates, args.output)
    print(json.dumps({"episodes": payload["episodes"], "replicates": payload["replicates_per_episode"], "runs": len(payload["rows"]), "aggregate_rows": len(payload["aggregate"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
