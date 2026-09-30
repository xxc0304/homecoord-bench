"""Generate clearly labelled HC-M06 synthetic traces for the import contract.

Fixtures exercise validation and scoring; they are not calibrated benchmark
episodes and must not be counted as independent household data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT
from probe_ventilation_heating_tradeoff import simulate
from runtime.physical_trace import score_trace, validate_matched_pair, validate_trace


SOURCE = {
    "kind": "synthetic_fixture",
    "revision": "hc-m06-standalone-thermal-probe-v1",
    "raw_data_reference": "generated_by:homecoord_bench/make_hc_m06_physical_trace_fixture.py",
    "calibration_status": "uncalibrated_placeholder",
    "license_note": "Self-generated research fixture; no third-party or device measurements.",
}
WORLD_ID = "hc-m06-synthetic-rate2p5-exchange0p0015"
PAIR_ID = "hc-m06-synthetic-pair-v1"
POLICIES = ("Independent", "ActionOverlapLock", "StateGate", "OracleSwitch")


def make_trace(condition: str, policy: str) -> tuple[dict, dict]:
    initial_co2 = 1600 if condition == "conflict" else 850
    run = simulate(initial_co2_ppm=initial_co2, ventilation_rate_ppm_s=2.5,
                   open_exchange_per_s=0.0015, deadline_ms=360000,
                   policy=policy, record_samples=True)
    trace = {
        "schema_version": "homecoord-physical-trace-0.1",
        "sampling_semantics": "interval_ending_at_t",
        "trace_id": f"{PAIR_ID}-{condition}-{policy}",
        "source": dict(SOURCE),
        "trial": {
            "pair_id": PAIR_ID,
            "world_config_id": WORLD_ID,
            "condition": condition,
            "policy": policy,
            "initial_temp_c": 17.0,
            "initial_co2_ppm": initial_co2,
            "outdoor_temp_c": 8.0,
            "initial_window_open": False,
            "initial_heater_power_kw": 0.0,
            "target_temp_c": 21.0,
            "target_co2_ppm": 900.0,
            "deadline_ms": 360000,
        },
        "events": run["events"],
        "samples": run["samples"],
    }
    return trace, run


def run(fixture_path: Path, audit_path: Path) -> dict:
    traces = []
    source_rows = {}
    for policy in POLICIES:
        for condition in ("conflict", "control"):
            trace, source_row = make_trace(condition, policy)
            errors = validate_trace(trace)
            if errors:
                raise ValueError(f"{trace['trace_id']}: {errors}")
            traces.append(trace)
            source_rows[(policy, condition)] = source_row
    scores = [score_trace(trace) for trace in traces]
    by_key = {(score["policy"], score["condition"]): score for score in scores}
    pairs = []
    for policy in POLICIES:
        conflict = next(trace for trace in traces if trace["trial"]["condition"] == "conflict" and trace["trial"]["policy"] == policy)
        control = next(trace for trace in traces if trace["trial"]["condition"] == "control" and trace["trial"]["policy"] == policy)
        errors = validate_matched_pair(conflict, control)
        if errors:
            raise ValueError(f"{policy} pair: {errors}")
        a, b = by_key[(policy, "conflict")], by_key[(policy, "control")]
        pairs.append({
            "policy": policy,
            "conflict_goal_completion_ms": a["observed_goal_completion_ms"],
            "control_goal_completion_ms": b["observed_goal_completion_ms"],
            "conflict_deadline_met": a["sampled_deadline_met"],
            "control_deadline_met": b["sampled_deadline_met"],
            "conflict_minus_control_heater_energy_wh": round(a["heater_energy_wh"] - b["heater_energy_wh"], 4),
            "conflict_minus_control_heater_energy_by_deadline_wh": round(
                a["heater_energy_by_deadline_wh"] - b["heater_energy_by_deadline_wh"], 4),
        })
    agreement = []
    for score in scores:
        row = source_rows[(score["policy"], score["condition"])]
        agreement.append({"trace_id": score["trace_id"],
                          "completion_matches_source": score["observed_goal_completion_ms"] == row["goal_completion_ms"],
                          "energy_difference_wh": round(score["heater_energy_wh"] - row["heater_energy_wh"], 4)})
    if not all(row["completion_matches_source"] and abs(row["energy_difference_wh"]) <= 0.0001 for row in agreement):
        raise AssertionError("trace-derived metrics diverge from fixture generator")
    fixture = {"schema_version": "homecoord-physical-trace-fixture-set-0.1",
               "status": "synthetic_uncalibrated_fixture_only", "traces": traces}
    audit = {"schema_version": "homecoord-physical-trace-fixture-audit-0.1",
             "status": "synthetic_uncalibrated_fixture_only",
             "traces_valid": len(traces), "matched_pairs_valid": len(pairs),
             "scores": scores, "pairs": pairs, "generator_score_agreement": agreement,
             "limitations": "These are eight policy/condition trajectories from one synthetic world, not eight homes or measured physical evidence. Condition controls change initial CO2 only; each policy has its own resulting trajectory."}
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path,
                        default=ROOT / "fixtures" / "physical_trace_v0.1" / "hc_m06_synthetic.json")
    parser.add_argument("--audit", type=Path,
                        default=ROOT / "results" / "physical_trace_fixture_audit_20260927.json")
    args = parser.parse_args()
    result = run(args.fixture, args.audit)
    print(json.dumps({"traces_valid": result["traces_valid"],
                      "matched_pairs_valid": result["matched_pairs_valid"],
                      "pairs": result["pairs"]}, ensure_ascii=False, indent=2))
