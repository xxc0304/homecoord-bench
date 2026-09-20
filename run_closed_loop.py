"""Run the seed episodes through the three minimal architectures."""

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
from runtime.replay_client import ReplayClient

ARCHITECTURES = ["CentralSingleAgent", "IndependentMultiAgent", "RuleCoordinator"]


def run(provider: str, output_dir: Path, replay_events: Path | None = None) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = EventLogger(output_dir / "model_events.jsonl", "deepseek-closed-loop") if provider == "deepseek" else None
    if provider == "dry-run":
        client = DryRunClient()
    elif provider == "deepseek":
        client = DeepSeekResponsesClient(logger=logger)
    elif provider == "replay":
        if replay_events is None:
            raise ValueError("replay provider requires --replay-events")
        client = ReplayClient(replay_events)
    else:
        raise ValueError(f"unsupported provider: {provider}")
    results = []
    for episode_path in sorted((ROOT / "data" / "seeds").glob("*.json")):
        episode = load_json(episode_path)
        for architecture in ARCHITECTURES:
            try:
                trace, result = run_closed_loop_episode(
                    episode,
                    client,
                    architecture,
                    INSTRUCTIONS,
                synthetic_latency=provider == "dry-run",
                )
            except Exception as exc:
                results.append({
                    "episode_id": episode["episode_id"],
                    "architecture": architecture,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                })
                continue
            trace_path = output_dir / f"{trace['trace_id']}.json"
            trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(result)
    (output_dir / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if provider == "replay":
        client.assert_consumed()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["dry-run", "deepseek", "replay"], default="dry-run")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "closed-loop")
    parser.add_argument("--replay-events", type=Path)
    args = parser.parse_args()
    rows = run(args.provider, args.output_dir, args.replay_events)
    compact = [
        {
            "episode_id": row["episode_id"],
            "architecture": row["architecture"],
            "process_valid_success": row.get("process_valid_success"),
            "conflicts": sum(row.get("conflict_counts", {}).values()),
            "first_action_ms": row.get("first_effective_action_latency_ms"),
            "completion_ms": row.get("task_completion_time_ms"),
            "error": row.get("error"),
        }
        for row in rows
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))
