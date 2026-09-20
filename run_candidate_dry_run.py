"""Run the first candidate task templates through all four deterministic architectures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.dry_run import DryRunClient
from runtime.execution import run_closed_loop_episode


ARCHITECTURES = [
    "CentralSingleAgent",
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
]


def run(output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for episode_path in sorted((ROOT / "data" / "candidates").glob("*.json")):
        episode = load_json(episode_path)
        for architecture in ARCHITECTURES:
            try:
                trace, result = run_closed_loop_episode(
                    episode,
                    DryRunClient(),
                    architecture,
                    INSTRUCTIONS,
                    synthetic_latency=True,
                )
                (output_dir / f"{trace['trace_id']}.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                rows.append(result)
            except Exception as exc:  # Keep the sweep auditable if one task is malformed.
                rows.append({
                    "episode_id": episode["episode_id"],
                    "architecture": architecture,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
    (output_dir / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "runs" / "candidate-dry-run-20260920",
    )
    args = parser.parse_args()
    rows = run(args.output_dir)
    compact = [
        {
            "episode_id": row["episode_id"],
            "architecture": row["architecture"],
            "process_valid_success": row.get("process_valid_success"),
            "conflicts": sum(row.get("conflict_counts", {}).values()),
            "first_action_ms": row.get("first_effective_action_latency_ms"),
            "completion_ms": row.get("task_completion_time_ms"),
            "service_rate": row.get("task_service_rate"),
            "error": row.get("error"),
        }
        for row in rows
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
