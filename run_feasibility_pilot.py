"""Small real-model feasibility pilot for the four conflict families."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.dry_run import DryRunClient
from runtime.event_log import EventLogger
from runtime.execution import run_closed_loop_episode


PILOT_TASKS = {
    "HC-M02": ("RuleCoordinator", "direct_device_conflict"),
    "HC-M07": ("ConstraintCoordinator", "indirect_environment_conflict"),
    "HC-M13": ("ConstraintCoordinator", "resource_capacity_conflict"),
    "HC-M18": ("RuleCoordinator", "stale_state_action"),
}
ARCHITECTURES = ("CentralSingleAgent", "IndependentMultiAgent")


def run(provider: str, model: str, repetitions: int, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = EventLogger(output_dir / "model_events.jsonl", f"feasibility-pilot-{provider}-{model}") if provider == "deepseek" else None
    client = DeepSeekResponsesClient(logger=logger, model=model) if provider == "deepseek" else DryRunClient()
    rows: list[dict] = []
    for episode_id, (coordinator, family) in PILOT_TASKS.items():
        episode = load_json(ROOT / "data" / "candidates" / f"{episode_id}.json")
        target_architectures = (*ARCHITECTURES, coordinator)
        for repetition in range(1, repetitions + 1):
            for architecture in target_architectures:
                run_episode = json.loads(json.dumps(episode))
                run_episode["episode_id"] = f"{episode_id}.pilot-{repetition:02d}-{architecture}"
                try:
                    trace, result = run_closed_loop_episode(
                        run_episode,
                        client,
                        architecture,
                        INSTRUCTIONS,
                        synthetic_latency=provider == "dry-run",
                    )
                    (output_dir / f"{trace['trace_id']}.json").write_text(
                        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    rows.append({"base_episode_id": episode_id, "task_family": family, **result})
                except Exception as exc:
                    rows.append({
                        "base_episode_id": episode_id,
                        "episode_id": run_episode["episode_id"],
                        "task_family": family,
                        "architecture": architecture,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                    })

    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["base_episode_id"], row["architecture"])].append(row)
    aggregate = []
    for (episode_id, architecture), items in sorted(grouped.items()):
        valid = [item for item in items if "error" not in item]
        aggregate.append({
            "base_episode_id": episode_id,
            "architecture": architecture,
            "runs": len(items),
            "errors": len(items) - len(valid),
            "process_valid_rate": (sum(item["process_valid_success"] for item in valid) / len(valid)) if valid else None,
            "final_goal_rate": (sum(item["final_goal_success"] for item in valid) / len(valid)) if valid else None,
            "mean_task_service_rate": (sum(item["task_service_rate"] for item in valid) / len(valid)) if valid else None,
            "conflict_counts": {
                key: sum(item.get("conflict_counts", {}).get(key, 0) for item in valid)
                for key in ("C1", "C2", "C3", "C4")
            },
            "first_action_ms": [item.get("first_effective_action_latency_ms") for item in valid],
            "completion_ms": [item.get("task_completion_time_ms") for item in valid],
        })
    payload = {
        "experiment": "real_model_feasibility_pilot",
        "provider": provider,
        "model": model,
        "repetitions": repetitions,
        "task_selection": PILOT_TASKS,
        "architectures": sorted(set(ARCHITECTURES) | {item[0] for item in PILOT_TASKS.values()}),
        "status": "feasibility_only",
        "aggregate": aggregate,
        "rows": rows,
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("dry-run", "deepseek"), default="deepseek")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "feasibility-pilot-deepseek-flash-20260920")
    args = parser.parse_args()
    payload = run(args.provider, args.model, args.repetitions, args.output_dir)
    print(json.dumps({
        "runs": len(payload["rows"]),
        "errors": sum("error" in row for row in payload["rows"]),
        "process_valid_successes": sum(bool(row.get("process_valid_success")) for row in payload["rows"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
