"""Scripted sanity baselines.

These baselines select hand-authored traces. They validate benchmark
discriminability; they are not LLM experiment results.
"""

from __future__ import annotations

import json
from collections import defaultdict
from statistics import median

from evaluate import ROOT, evaluate, load_json


TRACE_BY_SYSTEM = {
    "CentralSingleAgent": {
        "HC-SEED-001": "HC-SEED-001.serial.json",
        "HC-SEED-002": "HC-SEED-002.coordinated.json",
        "HC-SEED-003": "HC-SEED-003.sequenced.json",
        "HC-SEED-004": "HC-SEED-004.revalidated.json",
    },
    "IndependentMultiAgent": {
        "HC-SEED-001": "HC-SEED-001.parallel.json",
        "HC-SEED-002": "HC-SEED-002.conflict.json",
        "HC-SEED-003": "HC-SEED-003.overlap.json",
        "HC-SEED-004": "HC-SEED-004.stale.json",
    },
    "RuleCoordinator": {
        "HC-SEED-001": "HC-SEED-001.parallel.json",
        "HC-SEED-002": "HC-SEED-002.coordinated.json",
        "HC-SEED-003": "HC-SEED-003.overlap.json",
        "HC-SEED-004": "HC-SEED-004.revalidated.json",
    },
}


def run() -> dict:
    detail = []
    grouped = defaultdict(list)
    for system, cases in TRACE_BY_SYSTEM.items():
        for episode_id, trace_file in cases.items():
            episode = load_json(ROOT / "data" / "seeds" / f"{episode_id}.json")
            trace = load_json(ROOT / "traces" / trace_file)
            result = evaluate(episode, trace)
            result["system"] = system
            detail.append(result)
            grouped[system].append(result)

    summary = {}
    for system, rows in grouped.items():
        first = [row["first_effective_action_latency_ms"] for row in rows if row["first_effective_action_latency_ms"] is not None]
        completion = [row["task_completion_time_ms"] for row in rows if row["task_completion_time_ms"] is not None]
        summary[system] = {
            "episodes": len(rows),
            "final_goal_success_rate": sum(row["final_goal_success"] for row in rows) / len(rows),
            "process_valid_success_rate": sum(row["process_valid_success"] for row in rows) / len(rows),
            "total_conflicts": sum(sum(row["conflict_counts"].values()) for row in rows),
            "median_first_effective_action_latency_ms": median(first) if first else None,
            "median_task_completion_time_ms": median(completion) if completion else None,
        }
    return {"warning": "scripted sanity check; not an LLM experiment", "summary": summary, "detail": detail}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
