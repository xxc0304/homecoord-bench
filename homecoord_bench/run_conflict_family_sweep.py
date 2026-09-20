"""Run C2 indirect-conflict and C3 resource-capacity calibration families."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.dry_run import DryRunClient
from runtime.event_log import EventLogger
from runtime.execution import run_closed_loop_episode
from runtime.variants import indirect_conflict_variants, resource_capacity_variants

ARCHITECTURES = ("CentralSingleAgent", "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator")


def run(provider: str, output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = EventLogger(output_dir / "model_events.jsonl", f"conflict-family-{provider}") if provider == "deepseek" else None
    client = DeepSeekResponsesClient(logger=logger) if provider == "deepseek" else DryRunClient()
    episodes = [
        *indirect_conflict_variants(load_json(ROOT / "data" / "seeds" / "HC-SEED-003.json")),
        *resource_capacity_variants(load_json(ROOT / "data" / "seeds" / "HC-SEED-001.json")),
    ]
    rows = []
    for episode in episodes:
        for architecture in ARCHITECTURES:
            try:
                trace, result = run_closed_loop_episode(
                    episode,
                    client,
                    architecture,
                    INSTRUCTIONS,
                    synthetic_latency=provider == "dry-run",
                )
                (output_dir / f"{trace['trace_id']}.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                rows.append({**episode["variant"], **result})
            except Exception as exc:
                rows.append({
                    **episode["variant"],
                    "episode_id": episode["episode_id"],
                    "architecture": architecture,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                })
    (output_dir / "episodes.json").write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("dry-run", "deepseek"), default="dry-run")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "conflict-family-sweep")
    args = parser.parse_args()
    results = run(args.provider, args.output_dir)
    print(json.dumps([
        {
            "episode_id": row["episode_id"],
            "architecture": row["architecture"],
            "valid": row.get("process_valid_success"),
            "C2": row.get("conflict_counts", {}).get("C2"),
            "C3": row.get("conflict_counts", {}).get("C3"),
            "first_action_ms": row.get("first_effective_action_latency_ms"),
            "error": row.get("error"),
        }
        for row in results
    ], ensure_ascii=False, indent=2))
