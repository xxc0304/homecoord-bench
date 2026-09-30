"""C1/C3 paired baseline audit with a shared safety gate.

This is an author-side controlled mechanism experiment, not frozen benchmark
data or a physical-device study. No model API is called: the three C3 kitchen
proposal batches were saved by an earlier parallel DeepSeek pilot.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from runtime.dry_run import DryRunClient
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "results" / "core_paired_baselines_20260930.json"
C1_DIR = ROOT / "revision_drafts" / "20260927"
EV_DIR = ROOT / "data" / "pilot_pairs_v1"
KITCHEN_DIR = ROOT / "revision_drafts" / "20260929_c3_non_nested_review"
RECORDED = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
BASELINES = (
    "IndependentMultiAgent",
    "RuleCoordinator",
    "GateRetryRule",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
)


class FixedProposalClient(DryRunClient):
    def decide(self, request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        decision = super().decide(request, instructions)
        self.last_latency_ms = 300
        return decision


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _without_labels(value: dict[str, Any], *names: str) -> dict[str, Any]:
    out = deepcopy(value)
    for name in names:
        out.pop(name, None)
    return out


def _check_pairs() -> dict[str, dict[str, str]]:
    """Reject an unintended second experimental intervention."""
    c1a = C1_DIR / "HC-PAIR-C1-HVAC-CONFLICT.json"
    c1b = C1_DIR / "HC-PAIR-C1-HVAC-SAFE.json"
    a, b = _load(c1a), _load(c1b)
    assert a["task_stream"][1]["release_at_ms"] == 200
    assert b["task_stream"][1]["release_at_ms"] == 6200
    a["task_stream"][1]["release_at_ms"] = b["task_stream"][1]["release_at_ms"]
    assert _without_labels(a, "episode_id", "variant") == _without_labels(
        b, "episode_id", "variant"
    ), "C1 pair has another uncontrolled change"

    eva = EV_DIR / "HC-PAIR-C3-EV-WATER-CONFLICT.json"
    evb = EV_DIR / "HC-PAIR-C3-EV-WATER-CONTROL.json"
    a, b = _load(eva), _load(evb)
    assert a["home"]["resources"]["max_power_kw"] == 6.0
    assert b["home"]["resources"]["max_power_kw"] == 7.2
    a["home"]["resources"]["max_power_kw"] = b["home"]["resources"]["max_power_kw"]
    a["conflict_rules"][0]["capacity"] = b["conflict_rules"][0]["capacity"]
    assert _without_labels(a, "episode_id", "pair_condition") == _without_labels(
        b, "episode_id", "pair_condition"
    ), "EV/water pair has another uncontrolled change"

    kitchen_paths = [
        KITCHEN_DIR / f"HC-C3-KITCHEN_CIRCUIT-RHO-{pressure}.json"
        for pressure in ("0.8", "1.2", "1.6")
    ]
    kitchen = [_load(path) for path in kitchen_paths]
    reference = kitchen[0]
    for episode in kitchen[1:]:
        copy = deepcopy(episode)
        copy["home"]["resources"]["max_power_kw"] = reference["home"]["resources"]["max_power_kw"]
        copy["conflict_rules"][0]["capacity"] = reference["conflict_rules"][0]["capacity"]
        copy["resource_pressure"] = deepcopy(reference["resource_pressure"])
        assert _without_labels(copy, "episode_id") == _without_labels(
            reference, "episode_id"
        ), "kitchen pressure arms have another uncontrolled change"
    return {
        "C1_HVAC": {path.name: _sha(path) for path in (c1a, c1b)},
        "C3_EV_WATER": {path.name: _sha(path) for path in (eva, evb)},
        "C3_KITCHEN": {path.name: _sha(path) for path in kitchen_paths},
    }


def _score(family: str, condition: str, episode: dict[str, Any],
           policy: str, client: Any, proposal_batch: str,
           *, gate: bool = True) -> dict[str, Any]:
    trace, result = run_event_simulation(
        deepcopy(episode), client, policy, "controlled fixed-proposal audit",
        shared_safety_gate=gate,
    )
    if isinstance(client, MemoryReplayClient):
        client.assert_consumed()
    finishes = result["task_action_finish_time_ms"]
    all_served = bool(finishes) and all(value is not None for value in finishes.values())
    return {
        "family": family,
        "condition": condition,
        "episode_id": episode["episode_id"],
        "proposal_batch": proposal_batch,
        "policy": policy,
        "shared_safety_gate": gate,
        "first_safe_action_start_ms": result["first_action_start_latency_ms"] if gate else None,
        "first_action_start_ms": result["first_action_start_latency_ms"],
        "task_service": result["task_service"],
        "task_finish_ms": finishes,
        "all_tasks_served": all_served,
        "all_tasks_finished_ms": max(finishes.values()) if all_served else None,
        "all_deadlines_met": result["all_deadlines_met"] if family == "C3_KITCHEN" else None,
        "conflict_counts": result["conflict_counts"],
        "shared_gate_rejections": result["shared_safety_gate_rejection_count"],
        "constraint_violation_duration_ms": result["state_constraint_violation_duration_ms"],
        "rejection_reasons": [event["reason"] for event in trace["events"]
                              if event["type"] == "action_rejected"],
    }


def _fixed_rows(family: str, conditions: dict[str, Path]) -> list[dict[str, Any]]:
    rows = []
    for condition, path in conditions.items():
        episode = _load(path)
        for policy in BASELINES:
            rows.append(_score(family, condition, episode, policy,
                               FixedProposalClient(), "scripted-300ms"))
        # Unsafe execution is a diagnostic for B1, not a deployable baseline.
        rows.append(_score(family, condition, episode, "IndependentMultiAgent",
                           FixedProposalClient(), "scripted-300ms", gate=False))
    return rows


def _kitchen_rows() -> list[dict[str, Any]]:
    saved = _load(RECORDED)
    batches = [item for item in saved["batches"] if item["template_id"] == "KITCHEN_CIRCUIT"]
    assert len(batches) == 3 and all(not item["sample"]["errors"] for item in batches)
    rows = []
    for pressure in ("0.8", "1.2", "1.6"):
        path = KITCHEN_DIR / f"HC-C3-KITCHEN_CIRCUIT-RHO-{pressure}.json"
        episode = _load(path)
        for batch in batches:
            records = batch["sample"]["records"]
            assert set(records) == {task["task_id"] for task in episode["task_stream"]}
            ordered = [records[task["task_id"]] for task in episode["task_stream"]]
            for policy in (*BASELINES, "CapacityAwareDeadlineCoordinator"):
                rows.append(_score("C3_KITCHEN", f"rho={pressure}", episode, policy,
                                   MemoryReplayClient(deepcopy(ordered)),
                                   f"deepseek-flash-parallel-{batch['repetition']}"))
            rows.append(_score("C3_KITCHEN", f"rho={pressure}", episode,
                               "IndependentMultiAgent",
                               MemoryReplayClient(deepcopy(ordered)),
                               f"deepseek-flash-parallel-{batch['repetition']}", gate=False))
    return rows


def run(output: Path = RESULT) -> dict[str, Any]:
    hashes = _check_pairs()
    rows = _fixed_rows("C1_HVAC", {
        "overlap": C1_DIR / "HC-PAIR-C1-HVAC-CONFLICT.json",
        "nonoverlap": C1_DIR / "HC-PAIR-C1-HVAC-SAFE.json",
    })
    rows += _fixed_rows("C3_EV_WATER", {
        "capacity_low": EV_DIR / "HC-PAIR-C3-EV-WATER-CONFLICT.json",
        "capacity_high": EV_DIR / "HC-PAIR-C3-EV-WATER-CONTROL.json",
    })
    rows += _kitchen_rows()
    assert all(sum(item["conflict_counts"].values()) == 0 for item in rows
               if item["shared_safety_gate"]), "common gate allowed declared conflict"
    summary: dict[str, Any] = {}
    for family in ("C1_HVAC", "C3_EV_WATER", "C3_KITCHEN"):
        summary[family] = {}
        for condition in sorted({r["condition"] for r in rows if r["family"] == family}):
            subset = [r for r in rows if r["family"] == family and r["condition"] == condition]
            summary[family][condition] = {}
            for policy in sorted({r["policy"] for r in subset}):
                selected = [r for r in subset if r["policy"] == policy and r["shared_safety_gate"]]
                summary[family][condition][policy] = {
                    "runs": len(selected),
                    "all_tasks_served": sum(r["all_tasks_served"] for r in selected),
                    "all_deadlines_met": sum(r["all_deadlines_met"] for r in selected)
                    if family == "C3_KITCHEN" else None,
                    "median_first_safe_action_ms": median(
                        r["first_safe_action_start_ms"] for r in selected
                        if r["first_safe_action_start_ms"] is not None
                    ),
                    "median_all_tasks_finished_ms": median(
                        r["all_tasks_finished_ms"] for r in selected
                        if r["all_tasks_finished_ms"] is not None
                    ) if any(r["all_tasks_finished_ms"] is not None for r in selected) else None,
                    "gate_rejections": sum(r["shared_gate_rejections"] for r in selected),
                }
    report = {
        "schema_version": "core-paired-baselines-0.1",
        "status": "controlled_author_side_mechanism_probe_not_frozen_benchmark",
        "new_api_calls": 0,
        "physical_device_runs": 0,
        "pair_input_sha256": hashes,
        "saved_model_source_sha256": _sha(RECORDED),
        "assumptions": [
            "C1 temperature-goal success is excluded from this analysis; action duration and end-of-comfort flag remain synthetic.",
            "C3 EV/water durations and all capacities are controlled assumptions, not measured home limits.",
            "Kitchen proposal batches are three samples of one task template, not three independent tasks.",
            "A common start-time safety gate is applied to all deployable comparisons; ungated independent rows are diagnostics only.",
            "No synthetic coordination overhead is added; all first-action latency is proposal and simulator time.",
        ],
        "rows": rows,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    print(json.dumps({"rows": len(report["rows"]), "summary": report["summary"],
                      "output": str(RESULT)}, ensure_ascii=False, indent=2))
