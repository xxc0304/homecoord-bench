"""Prospectively fixed C3 candidate batch and paired scheduling replay.

The four task sets are author-designed controlled cases, not sampled homes.
No policy outcome is used to choose or tune a case. The ideal oracle is used
only to label intrinsic feasibility, never as an online policy.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_structural_generalization import (
    POLICIES, ScriptedProposalClient, TaskSpec, latencies_for_order,
    make_episode_from_specs,
)
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.scheduling_oracle import ideal_schedule


ROOT = Path(__file__).resolve().parent
OUTDIR = ROOT / "revision_drafts" / "20260930_c3_prospective_candidates"
RESULT = ROOT / "results" / "c3_prospective_candidates_20260930.json"
SEED = 20260930
PRESSURES = (0.8, 1.2, 1.6)
SAMPLE_TEMPLATE_INDICES = (1, 2)  # Locked before replay; not outcome-selected.
POOL = {
    "kettle": TaskSpec("boil_water", "BeverageAgent", "kettle", "boil", 1.8, 5, 12, 100),
    "cooktop": TaskSpec("cook_meal", "CookingAgent", "cooktop", "cook", 2.0, 25, 45, 80),
    "oven": TaskSpec("bake_meal", "BakingAgent", "oven", "bake", 3.0, 45, 85, 90),
    "dishwasher": TaskSpec("wash_dishes", "DishwashingAgent", "dishwasher", "wash", 2.4, 90, 190, 50),
    "washer": TaskSpec("wash_clothes", "LaundryAgent", "washer", "wash", 2.0, 60, 150, 60),
    "water_heater": TaskSpec("heat_water", "WaterHeatingAgent", "water_heater", "heat", 3.0, 45, 105, 95),
    "ev_charger": TaskSpec("charge_ev", "EVChargingAgent", "ev_charger", "charge", 3.3, 120, 240, 40),
    "heat_pump": TaskSpec("heat_home", "HeatingAgent", "heat_pump", "heat", 2.5, 60, 180, 70),
}


def template_specs() -> dict[str, tuple[TaskSpec, ...]]:
    rng = random.Random(SEED)
    names = tuple(POOL)
    return {
        f"P{index}": tuple(POOL[name] for name in rng.sample(names, 3))
        for index in range(1, 5)
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def prepare() -> dict[str, Any]:
    """Materialize all candidates and lock file hashes; no policy is run."""
    specs_by_template = template_specs()
    files: dict[str, str] = {}
    for template, specs in specs_by_template.items():
        for pressure in PRESSURES:
            path = OUTDIR / f"HC-C3-{template}-RHO-{pressure:g}.json"
            payload = make_episode_from_specs(f"PROSPECTIVE-{template}", specs, pressure)
            payload["source_type"] = "controlled_author_generated_prospective_candidate"
            payload["review_status"] = "unreviewed_mechanism_candidate"
            payload["scenario_assumptions"]["cross_task_dependencies"] = "none; every cycle is an independent service"
            _write_json(path, payload)
            files[path.name] = sha256(path)
    manifest = {
        "schema_version": "c3-prospective-candidate-manifest-0.1",
        "seed": SEED,
        "pool_order": list(POOL),
        "template_device_sets": {key: [item.device for item in value]
                                 for key, value in specs_by_template.items()},
        "controlled_task_specs": {key: vars(value) for key, value in POOL.items()},
        "pressures": list(PRESSURES),
        "policies": list(POLICIES),
        "arrival_orders": "all six permutations per template; 800/1000/1200 ms",
        "scripted_replay_cells": 4 * 3 * 6 * 4,
        "model_sample_templates": [f"P{index}" for index in SAMPLE_TEMPLATE_INDICES],
        "model_sample_repetitions": 2,
        "candidate_sha256": files,
        "status": "design_locked_before_oracle_and_policy_replay",
        "limitations": [
            "All powers, durations and deadlines are controlled settings, not measured household values.",
            "The same device may recur across templates; templates are not independent households.",
            "The sample subset is fixed before seeing replay outcomes.",
        ],
    }
    _write_json(OUTDIR / "manifest.json", manifest)
    return manifest


def load_locked() -> tuple[dict[str, Any], dict[tuple[str, float], dict[str, Any]]]:
    manifest = json.loads((OUTDIR / "manifest.json").read_text(encoding="utf-8"))
    episodes = {}
    for template in template_specs():
        for pressure in PRESSURES:
            path = OUTDIR / f"HC-C3-{template}-RHO-{pressure:g}.json"
            if sha256(path) != manifest["candidate_sha256"][path.name]:
                raise ValueError(f"candidate changed since design lock: {path}")
            episodes[template, pressure] = json.loads(path.read_text(encoding="utf-8"))
    return manifest, episodes


def preflight() -> dict[str, Any]:
    manifest, episodes = load_locked()
    rows = []
    for (template, pressure), episode in episodes.items():
        schedule = ideal_schedule(episode)
        for task in episode["task_stream"]:
            agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
            # Public alias avoids revealing pressure through the episode ID.
            sample = deepcopy(episode)
            sample["episode_id"] = f"HC-C3-PUBLIC-{template}"
            sample["base_episode_id"] = sample["episode_id"]
            request = build_agent_request(
                sample, agent, task, architecture="IndependentMultiAgent",
                current_time_ms=0, request_id=f"HC-C3-PUBLIC-{template}:{task['task_id']}",
            )
            text = json.dumps(request, ensure_ascii=False)
            other_ids = {t["task_id"] for t in episode["task_stream"]} - {task["task_id"]}
            if ("RHO" in text or "PROSPECTIVE" in text or "required_action" in text
                    or "action_template" in text or any(other in text for other in other_ids)
                    or request["goals"] or request["constraints"]):
                raise ValueError(f"information boundary failure: {template}, {task['task_id']}")
        rows.append({
            "template": template, "pressure": pressure,
            "oracle_feasible": schedule is not None,
            "oracle_schedule": schedule,
            "agent_requests_audited": len(episode["task_stream"]),
        })
    payload = {"manifest_sha256": sha256(OUTDIR / "manifest.json"), "rows": rows,
               "oracle_is_analysis_only": True}
    _write_json(OUTDIR / "preflight.json", payload)
    return payload


def replay() -> dict[str, Any]:
    manifest, episodes = load_locked()
    pre = json.loads((OUTDIR / "preflight.json").read_text(encoding="utf-8"))
    if pre["manifest_sha256"] != sha256(OUTDIR / "manifest.json"):
        raise ValueError("preflight belongs to a different locked manifest")
    rows = []
    for template, specs in template_specs().items():
        for order in itertools.permutations(tuple(task.task_id for task in specs)):
            latencies = latencies_for_order(order)
            for pressure in PRESSURES:
                episode = episodes[template, pressure]
                for policy in POLICIES:
                    trace, result = run_event_simulation(
                        deepcopy(episode), ScriptedProposalClient(latencies), policy,
                        "prospective candidate scripted proposal replay",
                        shared_safety_gate=True,
                    )
                    rows.append({
                        "template": template, "pressure": pressure,
                        "arrival_order": list(order), "policy": policy,
                        "first_safe_action_ms": result["first_action_start_latency_ms"],
                        "all_tasks_served": all(result["task_service"].values()),
                        "all_deadlines_met": result["all_deadlines_met"],
                        "task_service": result["task_service"],
                        "task_deadline_met": result["task_deadline_met"],
                        "task_finish_ms": result["task_action_finish_time_ms"],
                        "shared_gate_rejections": result["shared_safety_gate_rejection_count"],
                        "start_order": [e["task_id"] for e in trace["events"]
                                        if e["type"] == "action_started"],
                    })
    summary = {}
    for template in template_specs():
        summary[template] = {}
        for pressure in PRESSURES:
            key = f"{pressure:g}"
            feasibility = next(x["oracle_feasible"] for x in pre["rows"]
                               if x["template"] == template and x["pressure"] == pressure)
            summary[template][key] = {"oracle_feasible": feasibility}
            for policy in POLICIES:
                subset = [r for r in rows if r["template"] == template and
                          r["pressure"] == pressure and r["policy"] == policy]
                summary[template][key][policy] = {
                    "orders": len(subset),
                    "all_tasks_served": sum(r["all_tasks_served"] for r in subset),
                    "all_deadlines_met": sum(r["all_deadlines_met"] for r in subset),
                    "median_first_safe_action_ms": median(
                        r["first_safe_action_ms"] for r in subset
                        if r["first_safe_action_ms"] is not None),
                }
    payload = {
        "schema_version": "c3-prospective-candidate-replay-0.1",
        "manifest_sha256": sha256(OUTDIR / "manifest.json"),
        "candidate_sha256": manifest["candidate_sha256"],
        "status": "author_generated_controlled_probe_not_frozen_benchmark",
        "api_calls": 0, "rows": rows, "summary": summary,
        "analysis_unit": "template; pressure arms and arrival orders are paired interventions",
    }
    _write_json(RESULT, payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "preflight", "replay"))
    args = parser.parse_args()
    result = {"prepare": prepare, "preflight": preflight, "replay": replay}[args.stage]()
    print(json.dumps(result if args.stage == "prepare" else {
        "stage": args.stage, "rows": len(result.get("rows", [])),
        "summary": result.get("summary"),
    }, ensure_ascii=False, indent=2))
