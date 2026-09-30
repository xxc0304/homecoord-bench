"""Measure API-free local event-simulator wall time for coordination policies.

This times the Python simulation path (episode validation, scripted decisions,
scheduling, gate, trace, evaluation). Logged model latencies remain virtual and
are not waited on. It is not a production/device end-to-end latency measure.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_ev_water_event_gate import RecordedLatencyScriptedActions
from probe_physical_capacity_v2 import make_episode
from runtime.event_simulator import run_event_simulation

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "physical_capacity_v2.json"
OUTPUT = ROOT / "results" / "local_rule_runtime_benchmark_20260927.json"
WARMUP_RUNS = 300
SAMPLE_RUNS = 2000
POLICIES = ("ConstraintCoordinator", "DeadlineAwareCoordinator",
            "CapacityAwareDeadlineCoordinator")
SCENARIOS = (("conflict", 6.0), ("control", 7.2))


def percentile(sorted_values: list[int], p: float) -> int:
    return sorted_values[max(0, math.ceil(p * len(sorted_values)) - 1)]


def _run_once(episode: dict[str, Any], policy: str,
              latencies: dict[str, int]) -> int:
    started = time.perf_counter_ns()
    run_event_simulation(
        deepcopy(episode), RecordedLatencyScriptedActions(latencies),
        policy, "", shared_safety_gate=True,
    )
    return time.perf_counter_ns() - started


def run_benchmark(output: Path = OUTPUT) -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    latency_orders: dict[str, dict[str, int]] = {}
    for source_row in source["rows"]:
        records = source_row.get("model_records", {})
        if set(records) != {"charge_ev", "heat_water"}:
            continue
        latencies = {task_id: int(record["logical_latency_ms"])
                     for task_id, record in records.items()}
        first = min(latencies, key=latencies.get)
        latency_orders.setdefault(f"{first}_first", latencies)
    if set(latency_orders) != {"charge_ev_first", "heat_water_first"}:
        raise ValueError("source must contain both proposal-return orders")

    groups = []
    for condition, capacity in SCENARIOS:
        episode = make_episode(condition)
        episode["home"]["resources"]["max_power_kw"] = capacity
        next(rule for rule in episode["conflict_rules"] if rule["type"] == "C3")["capacity"] = capacity
        episode["home"]["resources"]["task_power_bounds_kw"] = {
            "charge_ev": 4.0, "heat_water": 3.0,
        }
        for proposal_order, latencies in latency_orders.items():
            for policy in POLICIES:
                for _ in range(WARMUP_RUNS):
                    _run_once(episode, policy, latencies)
                samples = [_run_once(episode, policy, latencies)
                           for _ in range(SAMPLE_RUNS)]
                ordered = sorted(samples)
                groups.append({
                    "condition": condition,
                    "capacity_kw": capacity,
                    "proposal_order": proposal_order,
                    "policy": policy,
                    "warmup_runs": WARMUP_RUNS,
                    "sample_runs": SAMPLE_RUNS,
                    "python_runtime_us": {
                        "median": round(statistics.median(samples) / 1000, 3),
                        "p95": round(percentile(ordered, 0.95) / 1000, 3),
                        "p99": round(percentile(ordered, 0.99) / 1000, 3),
                        "mean": round(statistics.mean(samples) / 1000, 3),
                    },
                    "recorded_proposal_virtual_latency_ms": latencies,
                })
    payload = {
        "schema_version": "local-rule-runtime-benchmark-0.1",
        "status": "measured_local_simulator_wall_clock_not_deployment_latency",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": source.get("source_sha256"),
        "timer": "time.perf_counter_ns",
        "timed_scope": "episode deepcopy + validation + scripted decisions + event coordination + safety gate + evaluation",
        "excluded_costs": ["LLM/API wall time", "network", "physical device command", "device feedback"],
        "virtual_proposal_latencies_are_waited_on": False,
        "coordination_delay_ms": 0,
        "new_api_calls": 0,
        "real_devices": 0,
        "groups": groups,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = run_benchmark()
    print(json.dumps({"groups": len(report["groups"]), "samples_per_group": SAMPLE_RUNS,
                      "output": str(OUTPUT)}, ensure_ascii=False))
