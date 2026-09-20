"""Aggregate one HomeCoord-Bench parameter sweep without hiding single-run limits."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from evaluate import evaluate, load_json
from runtime.variants import direct_conflict_variants, stale_action_variants


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "min": min(values) if values else None,
        "p50": median(values) if values else None,
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
        "mean": mean(values) if values else None,
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first_actions = [row["first_effective_action_latency_ms"] for row in rows if row.get("first_effective_action_latency_ms") is not None]
    completions = [row["task_completion_time_ms"] for row in rows if row.get("task_completion_time_ms") is not None]
    service_rates = [row["task_service_rate"] for row in rows if row.get("task_service_rate") is not None]
    success_count = sum(bool(row.get("process_valid_success")) for row in rows)
    conflict_episode_counts = {
        key: sum(row.get("conflict_counts", {}).get(key, 0) > 0 for row in rows)
        for key in ("C1", "C2", "C3", "C4")
    }
    return {
        "runs": len(rows),
        "process_valid_successes": success_count,
        "process_valid_success_rate": success_count / len(rows) if rows else None,
        "process_valid_success_rate_ci95_wilson": wilson_interval(success_count, len(rows)),
        "conflicts": {
            key: sum(row.get("conflict_counts", {}).get(key, 0) for row in rows)
            for key in ("C1", "C2", "C3", "C4")
        },
        "conflict_episode_counts": conflict_episode_counts,
        "conflict_episode_rate_ci95_wilson": {
            key: wilson_interval(count, len(rows))
            for key, count in conflict_episode_counts.items()
        },
        "first_effective_action_latency_ms": latency_summary(first_actions),
        "task_completion_time_ms": latency_summary(completions),
        "mean_task_service_rate": mean(service_rates) if service_rates else None,
    }


def analyze(run_dir: Path) -> dict[str, Any]:
    raw_rows = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parent
    if (run_dir / "episodes.json").exists():
        episodes = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
    else:
        episodes = [
            *direct_conflict_variants(load_json(root / "data" / "seeds" / "HC-SEED-002.json")),
            *stale_action_variants(load_json(root / "data" / "seeds" / "HC-SEED-004.json")),
        ]
    episode_by_id = {episode["episode_id"]: episode for episode in episodes}
    rows = []
    run_errors = []
    for raw in raw_rows:
        if "trace_id" not in raw:
            run_errors.append(raw)
            continue
        trace = load_json(run_dir / f"{raw['trace_id']}.json")
        refreshed = evaluate(episode_by_id[raw["episode_id"]], trace)
        rows.append({**raw, **refreshed})
    events = [
        json.loads(line)
        for line in (run_dir / "model_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    starts = [event for event in events if event["event_type"] == "model_call_started"]
    completed = [event for event in events if event["event_type"] == "model_call_completed"]
    failed = [event for event in events if event["event_type"] == "model_call_failed"]
    terminal = completed + failed

    by_request: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in terminal:
        by_request[event["request_id"]].append(event)
    logical_latencies = [sum(float(event.get("latency_ms") or 0) for event in request_events) for request_events in by_request.values()]
    successful_attempt_latencies = [float(event["latency_ms"]) for event in completed]

    token_totals = {
        "input": sum(int(event.get("input_tokens") or 0) for event in terminal),
        "output": sum(int(event.get("output_tokens") or 0) for event in terminal),
        "reasoning": sum(int(event.get("reasoning_tokens") or 0) for event in terminal),
    }
    token_totals["total"] = token_totals["input"] + token_totals["output"]

    by_architecture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    direct_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    stale_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    indirect_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    capacity_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    configuration_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_architecture[row["architecture"]].append(row)
        configuration_id = row.get("base_variant_id", row["episode_id"].split(".rep-", 1)[0])
        configuration_groups[(configuration_id, row["architecture"])].append(row)
        if row.get("family") == "direct_device_conflict":
            direct_groups[(row["architecture"], row["energy_visibility"])].append(row)
        elif row.get("family") == "stale_state_action":
            stale_groups[row["architecture"]].append(row)
        elif row.get("family") == "indirect_environment_conflict":
            indirect_groups[row["architecture"]].append(row)
        elif row.get("family") == "resource_capacity_conflict":
            capacity_groups[row["architecture"]].append(row)

    providers = sorted({event.get("provider") for event in starts if event.get("provider")})
    models = sorted({event.get("model") for event in starts if event.get("model")})
    reasoning_efforts = sorted({event.get("reasoning_effort") for event in starts if event.get("reasoning_effort")})
    model = models[0] if len(models) == 1 else models
    pricing = {
        "deepseek-flash": {"off_peak_input": 0.15, "off_peak_output": 0.60, "peak_multiplier": 2.0},
        "deepseek-v4-pro": {"off_peak_input": 0.66, "off_peak_output": 1.98, "peak_multiplier": 2.0},
    }.get(model if isinstance(model, str) else "")
    if pricing:
        input_cost_off_peak = token_totals["input"] * pricing["off_peak_input"] / 1_000_000
        output_cost_off_peak = token_totals["output"] * pricing["off_peak_output"] / 1_000_000
        estimated_cost = {
            "off_peak_all_input_cache_miss": input_cost_off_peak + output_cost_off_peak,
            "peak_all_input_cache_miss": pricing["peak_multiplier"] * (input_cost_off_peak + output_cost_off_peak),
            "pricing_source": "DeepSeek Models & Pricing page checked 2026-09-20; verify again before publication",
        }
    else:
        estimated_cost = {
            "off_peak_all_input_cache_miss": None,
            "peak_all_input_cache_miss": None,
            "pricing_source": f"no verified pricing configured for {model}",
        }
    repetitions = max((row.get("repetition", 1) for row in rows), default=0)
    return {
        "status": (
            "targeted repeated calibration; not a paper result"
            if repetitions > 1
            else "single-repetition parameter sweep; calibration evidence, not a paper result"
        ),
        "provider": providers[0] if len(providers) == 1 else providers,
        "model": model,
        "reasoning_effort": reasoning_efforts[0] if len(reasoning_efforts) == 1 else reasoning_efforts,
        "data_scope": {
            "variant_episodes": len({row["episode_id"] for row in rows}),
            "architecture_runs": len(raw_rows),
            "evaluated_runs": len(rows),
            "failed_runs": len(run_errors),
            "repetitions_per_configuration": repetitions,
        },
        "model_calls": {
            "logical_calls": len(by_request),
            "api_attempts": len(starts),
            "successful_logical_calls": sum(any(event["event_type"] == "model_call_completed" for event in request_events) for request_events in by_request.values()),
            "invalid_attempts": len(failed),
            "retry_successes": sum(
                any(event["event_type"] == "model_call_failed" for event in request_events)
                and any(event["event_type"] == "model_call_completed" for event in request_events)
                for request_events in by_request.values()
            ),
            "failure_types": [event.get("error_type") for event in failed],
        },
        "model_latency_ms": {
            "successful_attempt_only": latency_summary(successful_attempt_latencies),
            "logical_call_including_invalid_retry": latency_summary(logical_latencies),
        },
        "tokens_including_invalid_attempts": token_totals,
        "estimated_cost_usd": estimated_cost,
        "architectures": {name: summarize_rows(group) for name, group in sorted(by_architecture.items())},
        "configurations": {
            f"{configuration_id}.{architecture}": summarize_rows(group)
            for (configuration_id, architecture), group in sorted(configuration_groups.items())
        },
        "direct_conflict_by_visibility": {
            f"{architecture}.{visibility}": summarize_rows(group)
            for (architecture, visibility), group in sorted(direct_groups.items())
        },
        "stale_action_by_event_time": {
            architecture: [
                {
                    "resident_enter_at_ms": row["resident_enter_at_ms"],
                    "process_valid_success": row["process_valid_success"],
                    "C4": row["conflict_counts"]["C4"],
                    "first_effective_action_latency_ms": row["first_effective_action_latency_ms"],
                    "task_completion_time_ms": row["task_completion_time_ms"],
                    "rejected_action_count": row["rejected_action_count"],
                }
                for row in sorted(group, key=lambda item: item["resident_enter_at_ms"])
            ]
            for architecture, group in sorted(stale_groups.items())
        },
        "indirect_conflict_by_task_gap": {
            architecture: [
                {
                    "second_task_gap_ms": row["second_task_gap_ms"],
                    "process_valid_success": row["process_valid_success"],
                    "C2": row["conflict_counts"]["C2"],
                    "first_effective_action_latency_ms": row["first_effective_action_latency_ms"],
                    "task_completion_time_ms": row["task_completion_time_ms"],
                }
                for row in sorted(group, key=lambda item: item["second_task_gap_ms"])
            ]
            for architecture, group in sorted(indirect_groups.items())
        },
        "resource_conflict_by_capacity": {
            architecture: [
                {
                    "capacity_kw": row["capacity_kw"],
                    "process_valid_success": row["process_valid_success"],
                    "C3": row["conflict_counts"]["C3"],
                    "first_effective_action_latency_ms": row["first_effective_action_latency_ms"],
                    "task_completion_time_ms": row["task_completion_time_ms"],
                }
                for row in sorted(group, key=lambda item: item["capacity_kw"])
            ]
            for architecture, group in sorted(capacity_groups.items())
        },
        "episodes": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = analyze(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "data_scope", "model_calls", "model_latency_ms", "tokens_including_invalid_attempts", "estimated_cost_usd")}, ensure_ascii=False, indent=2))
