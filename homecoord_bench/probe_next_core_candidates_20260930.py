"""Evaluate the preregistered C1 command and C3 laundry review candidates."""

from __future__ import annotations

import hashlib
import itertools
import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from probe_c3_structural_generalization import ScriptedProposalClient, latencies_for_order
from probe_core_paired_baselines_20260930 import FixedProposalClient
from runtime.event_simulator import run_event_simulation


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "revision_drafts" / "20260930_core_review"
RESULT = ROOT / "results" / "next_core_candidates_20260930.json"
SOURCE_V02 = ROOT / "revision_drafts" / "20260930_core_review_v02"
RESULT_V02 = ROOT / "results" / "c3_laundry_feasible_v02_20260930.json"
LOCKED_SHA256 = {
    "HC-C1-COMMAND-NONOVERLAP.json": "9BEBF604656A1869EE5BD0EBBBBEDDA064510798722E6F69216E37037E6F19F8",
    "HC-C1-COMMAND-OVERLAP.json": "48EC01AA3016116B6417C0EBEEDFAF760E67C802D657AA83279C9A71003D9327",
    "HC-C3-LAUNDRY_HEAT-RHO-0.8.json": "B82A9C34DC30DB13DA6DD3386352A44B3A3976584B96DCB7342A7151410B5E67",
    "HC-C3-LAUNDRY_HEAT-RHO-1.2.json": "ECA2EBCF32C1B33B20B5A59ECE5E7EF600BE6EB585F68FA759B2331E8BF57374",
    "HC-C3-LAUNDRY_HEAT-RHO-1.6.json": "E01E4A6E8629394760C109B15D20A7CE2CC6CE4B1C2357C664BAA0F8448DFAEB",
}
POLICIES = (
    "IndependentMultiAgent",
    "RuleCoordinator",
    "GateRetryRule",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
)
LOCKED_SHA256_V02 = {
    "HC-C3-LAUNDRY_HEAT_V02-RHO-0.8.json": "E2554202519ADAB805B3A0A96F0EBB5F69EA0D8329037315EE9F09220069051D",
    "HC-C3-LAUNDRY_HEAT_V02-RHO-1.2.json": "4A023AB00EE21BF736811D4BDA352AE7177F29AA79DD217FC07894246CDBDF2F",
    "HC-C3-LAUNDRY_HEAT_V02-RHO-1.6.json": "0271687AD0385F5B150F5371E44B2A9A7A5FDF5425D798A028012727063BA4A0",
}


def _load(name: str) -> dict[str, Any]:
    path = SOURCE / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if digest != LOCKED_SHA256[name]:
        raise ValueError(f"preregistered input changed: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_isolation(c1: list[dict[str, Any]], c3: list[dict[str, Any]]) -> None:
    a, b = deepcopy(c1)
    a["task_stream"][1]["release_at_ms"] = b["task_stream"][1]["release_at_ms"]
    a.pop("episode_id")
    b.pop("episode_id")
    a.pop("variant")
    b.pop("variant")
    assert a == b, "C1 has a second changed factor"
    reference = deepcopy(c3[0])
    reference.pop("episode_id")
    reference.pop("variant")
    for original in c3[1:]:
        copy = deepcopy(original)
        copy.pop("episode_id")
        copy.pop("variant")
        copy["home"]["resources"]["max_power_kw"] = reference["home"]["resources"]["max_power_kw"]
        copy["conflict_rules"][0]["capacity"] = reference["conflict_rules"][0]["capacity"]
        copy["resource_pressure"] = deepcopy(reference["resource_pressure"])
        assert copy == reference, "C3 has a second changed factor"


def _one(episode: dict[str, Any], condition: str, proposal_order: str,
         policy: str, client: Any, *, gate: bool = True) -> dict[str, Any]:
    trace, result = run_event_simulation(
        deepcopy(episode), client, policy, "preregistered controlled candidate probe",
        shared_safety_gate=gate,
    )
    service = result["task_service"]
    finish = result["task_action_finish_time_ms"]
    all_served = bool(service) and all(service.values())
    return {
        "episode_id": episode["episode_id"],
        "condition": condition,
        "proposal_order": proposal_order,
        "policy": policy,
        "shared_safety_gate": gate,
        "task_service": service,
        "all_tasks_served": all_served,
        "task_action_finish_time_ms": finish,
        "all_tasks_finished_ms": max(finish.values()) if all_served else None,
        "all_deadlines_met": result["all_deadlines_met"] if condition.startswith("rho=") else None,
        "first_action_start_ms": result["first_action_start_latency_ms"],
        "conflict_counts": result["conflict_counts"],
        "gate_rejections": result["shared_safety_gate_rejection_count"],
        "state_constraint_violation_duration_ms": result["state_constraint_violation_duration_ms"],
        "rejection_reasons": [event["reason"] for event in trace["events"]
                              if event["type"] == "action_rejected"],
    }


def run(output: Path = RESULT) -> dict[str, Any]:
    c1 = [_load(f"HC-C1-COMMAND-{name}.json") for name in ("OVERLAP", "NONOVERLAP")]
    c3 = [_load(f"HC-C3-LAUNDRY_HEAT-RHO-{pressure}.json")
          for pressure in ("0.8", "1.2", "1.6")]
    _check_isolation(c1, c3)
    rows: list[dict[str, Any]] = []
    for episode in c1:
        condition = episode["variant"]["condition"]
        for policy in POLICIES:
            rows.append(_one(episode, condition, "scripted-300ms", policy,
                             FixedProposalClient()))
        rows.append(_one(episode, condition, "scripted-300ms", "IndependentMultiAgent",
                         FixedProposalClient(), gate=False))
    task_ids = tuple(task["task_id"] for task in c3[0]["task_stream"])
    for order in itertools.permutations(task_ids):
        latencies = latencies_for_order(order)
        order_label = ",".join(order)
        for episode in c3:
            condition = episode["variant"]["condition"]
            for policy in (*POLICIES, "CapacityAwareDeadlineCoordinator"):
                rows.append(_one(episode, condition, order_label, policy,
                                 ScriptedProposalClient(latencies)))
            rows.append(_one(episode, condition, order_label, "IndependentMultiAgent",
                             ScriptedProposalClient(latencies), gate=False))
    assert all(sum(row["conflict_counts"].values()) == 0 for row in rows
               if row["shared_safety_gate"]), "common safety gate allowed declared conflict"
    summary: dict[str, Any] = {}
    for condition in ("overlap", "nonoverlap", "rho=0.8", "rho=1.2", "rho=1.6"):
        summary[condition] = {}
        for policy in (*POLICIES, "CapacityAwareDeadlineCoordinator"):
            selected = [row for row in rows if row["condition"] == condition
                        and row["policy"] == policy and row["shared_safety_gate"]]
            if not selected:
                continue
            summary[condition][policy] = {
                "runs": len(selected),
                "all_tasks_served": sum(row["all_tasks_served"] for row in selected),
                "all_deadlines_met": sum(row["all_deadlines_met"] for row in selected)
                if condition.startswith("rho=") else None,
                "median_first_action_start_ms": median(row["first_action_start_ms"]
                                                        for row in selected),
                "gate_rejections": sum(row["gate_rejections"] for row in selected),
            }
    report = {
        "schema_version": "next-core-candidate-probe-0.1",
        "status": "preregistered_author_side_controlled_probe_not_frozen_benchmark",
        "new_model_api_calls": 0,
        "preregistered_input_sha256": LOCKED_SHA256,
        "rows": rows,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def run_v02(output: Path = RESULT_V02) -> dict[str, Any]:
    """Replay the separately versioned feasibility repair without changing v0.1."""
    from runtime.scheduling_oracle import ideal_schedule

    episodes = []
    for pressure in ("0.8", "1.2", "1.6"):
        name = f"HC-C3-LAUNDRY_HEAT_V02-RHO-{pressure}.json"
        path = SOURCE_V02 / name
        if hashlib.sha256(path.read_bytes()).hexdigest().upper() != LOCKED_SHA256_V02[name]:
            raise ValueError(f"v0.2 preregistered input changed: {name}")
        episode = json.loads(path.read_text(encoding="utf-8"))
        if ideal_schedule(episode) is None:
            raise ValueError(f"v0.2 became infeasible: {name}")
        episodes.append(episode)
    reference = deepcopy(episodes[0])
    reference.pop("episode_id")
    reference.pop("variant")
    for episode in episodes[1:]:
        copy = deepcopy(episode)
        copy["home"]["resources"]["max_power_kw"] = reference["home"]["resources"]["max_power_kw"]
        copy["conflict_rules"][0]["capacity"] = reference["conflict_rules"][0]["capacity"]
        copy["resource_pressure"] = deepcopy(reference["resource_pressure"])
        copy.pop("episode_id")
        copy.pop("variant")
        assert copy == reference, "v0.2 pressure arms have a second changed factor"
    task_ids = tuple(task["task_id"] for task in episodes[0]["task_stream"])
    rows = []
    for order in itertools.permutations(task_ids):
        latencies = latencies_for_order(order)
        for episode in episodes:
            condition = episode["variant"]["condition"]
            for policy in (*POLICIES, "CapacityAwareDeadlineCoordinator"):
                rows.append(_one(episode, condition, ",".join(order), policy,
                                 ScriptedProposalClient(latencies)))
            rows.append(_one(episode, condition, ",".join(order),
                             "IndependentMultiAgent", ScriptedProposalClient(latencies),
                             gate=False))
    summary = {}
    for condition in ("rho=0.8", "rho=1.2", "rho=1.6"):
        summary[condition] = {}
        for policy in (*POLICIES, "CapacityAwareDeadlineCoordinator"):
            selected = [row for row in rows if row["condition"] == condition
                        and row["policy"] == policy and row["shared_safety_gate"]]
            summary[condition][policy] = {
                "runs": len(selected),
                "all_tasks_served": sum(row["all_tasks_served"] for row in selected),
                "all_deadlines_met": sum(row["all_deadlines_met"] for row in selected),
                "median_first_action_start_ms": median(row["first_action_start_ms"]
                                                        for row in selected),
            }
    report = {
        "schema_version": "c3-laundry-feasible-v02-probe-0.1",
        "status": "post_v01_feasibility_repair_exploratory_not_independent_holdout",
        "new_model_api_calls": 0,
        "preregistered_input_sha256": LOCKED_SHA256_V02,
        "rows": rows,
        "summary": summary,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps({"rows": len(report["rows"]), "summary": report["summary"],
                      "output": str(RESULT)}, ensure_ascii=False, indent=2))
