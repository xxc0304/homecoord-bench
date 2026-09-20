"""Repeat only the calibration configurations that distinguish mechanisms."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.dry_run import DryRunClient
from runtime.event_log import EventLogger
from runtime.execution import run_closed_loop_episode
from runtime.variants import (
    direct_conflict_variants,
    indirect_conflict_variants,
    resource_capacity_variants,
    stale_action_variants,
)


CORE_TARGETS = (
    ("HC-VAR-002-policy_visible-0", "IndependentMultiAgent"),
    ("HC-VAR-002-local_only-0", "IndependentMultiAgent"),
    ("HC-VAR-002-local_only-0", "RuleCoordinator"),
    ("HC-VAR-004-enter-800", "IndependentMultiAgent"),
    ("HC-VAR-004-enter-800", "RuleCoordinator"),
    ("HC-VAR-004-enter-1500", "RuleCoordinator"),
)

CONFLICT_TARGETS = (
    ("HC-VAR-003-gap-1000", "IndependentMultiAgent"),
    ("HC-VAR-003-gap-1000", "ConstraintCoordinator"),
    ("HC-VAR-003-gap-1500", "IndependentMultiAgent"),
    ("HC-VAR-003-gap-1500", "ConstraintCoordinator"),
    ("HC-VAR-001-cap-1p21", "IndependentMultiAgent"),
    ("HC-VAR-001-cap-1p21", "ConstraintCoordinator"),
    ("HC-VAR-001-cap-1p23", "IndependentMultiAgent"),
    ("HC-VAR-001-cap-1p23", "ConstraintCoordinator"),
)

TARGETS = CORE_TARGETS + CONFLICT_TARGETS


def calibration_variants() -> dict[str, dict]:
    variants = [
        *direct_conflict_variants(load_json(ROOT / "data" / "seeds" / "HC-SEED-002.json")),
        *stale_action_variants(load_json(ROOT / "data" / "seeds" / "HC-SEED-004.json")),
        *indirect_conflict_variants(load_json(ROOT / "data" / "seeds" / "HC-SEED-003.json")),
        *resource_capacity_variants(load_json(ROOT / "data" / "seeds" / "HC-SEED-001.json")),
    ]
    return {episode["episode_id"]: episode for episode in variants}


def run(
    provider: str,
    repetitions: int,
    output_dir: Path,
    targets: tuple[tuple[str, str], ...] = TARGETS,
    model: str | None = None,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_label = f"targeted-repetitions-{provider}-{model or 'default'}"
    logger = EventLogger(output_dir / "model_events.jsonl", run_label) if provider == "deepseek" else None
    client = DeepSeekResponsesClient(logger=logger, model=model or "deepseek-flash") if provider == "deepseek" else DryRunClient()
    variants = calibration_variants()
    rows = []
    materialized_episodes = []

    for base_variant_id, architecture in targets:
        for repetition in range(1, repetitions + 1):
            episode = deepcopy(variants[base_variant_id])
            episode["base_variant_id"] = base_variant_id
            episode["episode_id"] = f"{base_variant_id}.rep-{repetition:02d}"
            episode["variant"] = {**episode["variant"], "repetition": repetition}
            materialized_episodes.append(episode)
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
                rows.append({
                    **episode["variant"],
                    "base_variant_id": base_variant_id,
                    **result,
                })
            except Exception as exc:
                rows.append({
                    **episode["variant"],
                    "base_variant_id": base_variant_id,
                    "episode_id": episode["episode_id"],
                    "architecture": architecture,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                })

    (output_dir / "episodes.json").write_text(
        json.dumps(materialized_episodes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("dry-run", "deepseek"), default="dry-run")
    parser.add_argument("--model", help="override the DeepSeek model")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "targeted-repetitions")
    parser.add_argument("--suite", choices=("core", "c2c3", "all"), default="core")
    parser.add_argument(
        "--target", action="append",
        choices=[f"{variant_id}|{architecture}" for variant_id, architecture in TARGETS],
        help="repeat one selected calibration configuration; may be passed more than once",
    )
    args = parser.parse_args()
    suites = {"core": CORE_TARGETS, "c2c3": CONFLICT_TARGETS, "all": TARGETS}
    selected = tuple(tuple(item.split("|", 1)) for item in args.target) if args.target else suites[args.suite]
    rows = run(args.provider, args.repetitions, args.output_dir, selected, args.model)
    print(json.dumps({
        "runs": len(rows),
        "errors": sum("error" in row for row in rows),
        "process_valid_successes": sum(bool(row.get("process_valid_success")) for row in rows),
    }, ensure_ascii=False, indent=2))
