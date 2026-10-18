"""Re-audit the twelve proposed structures without model/API calls.

This is a mechanism and evidence-readiness audit, not a benchmark score.
It replays only structures with executable local contracts and marks the
remaining designs as unimplemented rather than manufacturing outcomes.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from generate_provenance_pilot import build as provenance_episodes
from probe_c2_recorded_model_physics import replay_row as c2_replay
from probe_c3_three_load_model import replay_records as c3_replay
from probe_c4_agent_message import replay_row as c4_replay
from probe_m03_coupled_mechanism import run as m03_run
from probe_m02_dependency_capacity import run as m02_run
from runtime.dry_run import DryRunClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "pilot_structure_reaudit_20260928.json"
POLICIES = (
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
    "CapacityAwareDeadlineCoordinator",
    "CentralSingleAgent",
)
NEW_SYNTHETIC_PROBES = {
    "M04": ("m04_joint_environment_synthetic_20260928.json",
            "joint CO2/temperature/power trajectory still uncalibrated; no reviewed benchmark episode"),
    "M05": ("m05_multiroom_synthetic_20260928.json",
            "two distinct room-response hypotheses but no measured room model or resident demand source"),
    "M06": ("m06_d02_dynamic_contracts_20260928.json",
            "power modes, stop acknowledgement and restart loss are hypothetical device contracts"),
    "D02": ("m06_d02_dynamic_contracts_20260928.json",
            "capacity cause, energy-report latency and physical load-shed acknowledgement are hypothetical"),
    "D03": ("d03_return_message_synthetic_20260928.json",
            "message-to-HVAC release is executable; return-service window and real latency unverified"),
}


def load_result(name: str) -> tuple[dict, dict]:
    path = ROOT / "results" / name
    raw = path.read_bytes()
    return json.loads(raw), {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest()}


def normalized_c2(row: dict) -> dict:
    # heat_rate_c_per_s was added to replay output after this result was saved.
    return {key: value for key, value in row.items() if key != "heat_rate_c_per_s"}


def run_audit() -> dict:
    report: dict = {
        "schema_version": "pilot-structure-reaudit-v0.1",
        "status": "exploratory_mechanism_and_readiness_only",
        "api_calls": 0,
        "structures": {},
        "sources": [],
    }

    generated = provenance_episodes()
    assert len(generated) == 5
    for structure, prefix in (("B01", "HC-PROV-C1-"), ("B03", "HC-PROV-C3-")):
        rows = []
        for episode in generated:
            if not episode["episode_id"].startswith(prefix):
                continue
            issues = validate_event_episode(episode)
            if issues:
                raise ValueError((episode["episode_id"], issues))
            for policy in POLICIES:
                trace, result = run_event_simulation(
                    deepcopy(episode), DryRunClient(), policy, "",
                    shared_safety_gate=True,
                )
                rows.append({
                    "episode_id": episode["episode_id"],
                    "policy": policy,
                    "data_tier": episode["data_tier"],
                    "process_valid_success": result["process_valid_success"],
                    "task_service": result["task_service"],
                    "all_deadlines_met": result["all_deadlines_met"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                    "action_rejections": [
                        event.get("reason") for event in trace["events"]
                        if event["type"] == "action_rejected"
                    ],
                })
        report["structures"][structure] = {
            "readiness": "partial_executable_synthetic_mechanism",
            "episode_count": len(rows) // len(POLICIES),
            "policy_run_count": len(rows),
            "missing": (
                "critical arrival boundary and independent task/parameter review"
                if structure == "B01" else
                "verified capacity implementation point, matched device profiles and human deadlines"
            ),
            "rows": rows,
        }

    c2, source = load_result("c2_recorded_model_physics_20260928.json")
    report["sources"].append(source)
    c2_rows = [x for row in c2["rows"] for x in c2_replay(row)]
    c2_ok = len(c2_rows) == len(c2["replays"]) and all(
        normalized_c2(a) == b for a, b in zip(c2_rows, c2["replays"])
    )
    report["structures"]["B02"] = {
        "readiness": "partial_executable_uncalibrated_physics",
        "proposal_samples_same_template": len(c2["rows"]),
        "replay_rows": len(c2_rows),
        "saved_outcomes_reproduced": c2_ok,
        "schema_note": "Current replay adds heat_rate_c_per_s metadata; all archived numerical and decision fields match.",
        "missing": "joint environmental calibration; critical CO2 condition and independent homes",
    }

    c3, source = load_result("c3_three_load_model_pilot_20260928.json")
    report["sources"].append(source)
    c3_rows = [
        x for row in c3["rows"]
        for x in c3_replay(row["model_records"], row["repetition"])
    ]
    report["structures"]["M01"] = {
        "readiness": "partial_executable_fixed_cycle_synthetic",
        "proposal_samples_same_template": len(c3["rows"]),
        "replay_rows": len(c3_rows),
        "saved_outcomes_reproduced": c3_rows == c3["replays"],
        "missing": "phase power/actual capacity and deadline provenance; critical capacity arm",
    }

    c4, source = load_result("c4_agent_message_pilot_20260928.json")
    report["sources"].append(source)
    clean, clean_source = load_result("c4_recorded_proposal_boundary_20260928.json")
    report["sources"].append(clean_source)
    if hashlib.sha256((ROOT / "results" / "c4_recorded_proposal_boundary_20260928.json").read_bytes()).hexdigest() != c4["clean_source_sha256"]:
        raise ValueError("C4 cleaning proposal source hash changed")
    clean_by_rep = {row["repetition"]: row for row in clean["rows"]}
    c4_rows = [
        x for row in c4["rows"]
        for x in c4_replay(row, clean_by_rep[row["repetition"]])
    ]
    report["structures"]["D01"] = {
        "readiness": "partial_executable_post_event_message_only",
        "proposal_samples_same_template": len(c4["rows"]),
        "replay_rows": len(c4_rows),
        "saved_outcomes_reproduced": c4_rows == c4["replays"],
        "missing": "advance-notice arms, grounded robot stop acknowledgement and independently sourced occupancy events",
    }

    m02_saved, source = load_result("m02_dependency_capacity_20260928.json")
    report["sources"].append(source)
    m02_current = m02_run()
    report["structures"]["M02"] = {
        "readiness": "partial_executable_synthetic_completion_trigger",
        "episode_count": len(m02_current["episodes"]),
        "replay_rows": len(m02_current["rows"]),
        "saved_outcomes_reproduced": m02_current["rows"] == m02_saved["rows"],
        "missing": "reviewed cycle powers/deadlines and early reservation information contract",
    }

    m03_saved, source = load_result("m03_c1_c3_coupled_mechanism_20260928.json")
    report["sources"].append(source)
    m03_current = m03_run()
    report["structures"]["M03"] = {
        "readiness": "partial_executable_synthetic_coupled_mechanism",
        "episode_count": len(m03_current["episodes"]),
        "replay_rows": len(m03_current["rows"]),
        "saved_outcomes_reproduced": m03_current["rows"] == m03_saved["rows"],
        "missing": "independent review of energy service, actual capacity and EV/HVAC timing",
    }

    for structure, (filename, reason) in NEW_SYNTHETIC_PROBES.items():
        saved, source = load_result(filename)
        if source not in report["sources"]:
            report["sources"].append(source)
        rows = [row for row in saved["rows"] if row.get("structure") == structure] if structure in {"M06", "D02"} else saved["rows"]
        if not rows or saved.get("api_calls") != 0:
            raise ValueError(f"{structure}: missing offline synthetic probe")
        report["structures"][structure] = {
            "readiness": "synthetic_probe_no_reviewed_benchmark_episode",
            "replay_rows": len(rows),
            "source_result": source["path"],
            "missing": reason,
        }

    expected = {"B01", "B02", "B03", *(f"M{i:02d}" for i in range(1, 7)),
                *(f"D{i:02d}" for i in range(1, 4))}
    if set(report["structures"]) != expected:
        raise ValueError("structure coverage mismatch")
    report["all_existing_replays_reproduced"] = all(
        report["structures"][key]["saved_outcomes_reproduced"]
        for key in ("B02", "M01", "M02", "M03", "D01")
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_audit()
    print(json.dumps({
        "structures": len(result["structures"]),
        "partially_executable": sum(
            "partial_executable" in item["readiness"]
            for item in result["structures"].values()
        ),
        "design_only": sum(
            item["readiness"] == "design_only_no_executable_episode"
            for item in result["structures"].values()
        ),
        "new_synthetic_probe_only": sum(
            item["readiness"] == "synthetic_probe_no_reviewed_benchmark_episode"
            for item in result["structures"].values()
        ),
        "all_existing_replays_reproduced": result["all_existing_replays_reproduced"],
        "output": str(OUT),
    }, ensure_ascii=False))


