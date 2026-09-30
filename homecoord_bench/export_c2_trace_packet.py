"""Export and self-audit representative HC-M06 C2 simulator trajectories.

These are synthetic, uncalibrated traces intended for reviewer inspection.
They do not enter the benchmark score set.
"""

from __future__ import annotations

import json
import math
import hashlib
from pathlib import Path

from probe_ventilation_heating_tradeoff import POLICIES, simulate
from evaluate import ROOT


OUTPUT = ROOT / "results" / "c2_representative_trace_packet_20260927.json"
CONFIGS = (
    {"condition": "conflict", "initial_co2_ppm": 1600,
     "ventilation_rate_ppm_s": 2.5, "open_exchange_per_s": 0.0015,
     "deadline_ms": 360000},
    {"condition": "matched_control", "initial_co2_ppm": 850,
     "ventilation_rate_ppm_s": 2.5, "open_exchange_per_s": 0.0015,
     "deadline_ms": 360000},
)


def audit_trace(result: dict) -> dict:
    samples = result.get("samples", [])
    errors: list[str] = []
    if not samples:
        return {"valid": False, "errors": ["no_samples"]}
    for left, right in zip(samples, samples[1:]):
        dt = right["t_ms"] - left["t_ms"]
        if dt <= 0:
            errors.append("non_monotonic_sample_clock")
            continue
        # The probe documents that each sample row after t=0 describes the
        # interval ending at that row's t_ms. Boundary events at interval start
        # therefore apply to the right-hand sample.
        if not right["window_open"] and right["co2_ppm"] != left["co2_ppm"]:
            errors.append("co2_changed_while_window_closed")
        if right["window_open"] and right["co2_ppm"] > left["co2_ppm"] + 1e-6:
            errors.append("co2_increased_while_window_open")
        if right["window_open"] and right["heater_power_kw"] == 0:
            if right["indoor_temp_c"] > left["indoor_temp_c"] + 1e-6:
                errors.append("temperature_increased_with_open_window_and_heater_off")
        if right["heater_power_kw"] not in (0.0, 2.0):
            errors.append("unexpected_heater_power")
    observed_heater_wh = sum(
        right["heater_power_kw"] * (right["t_ms"] - left["t_ms"]) / 3_600
        for left, right in zip(samples, samples[1:])
    )
    observed_window_heater_wh = sum(
        right["heater_power_kw"] * (right["t_ms"] - left["t_ms"]) / 3_600
        for left, right in zip(samples, samples[1:])
        if right["window_open"]
    )
    if not math.isclose(observed_heater_wh, result["heater_energy_wh"], abs_tol=0.001):
        errors.append("heater_energy_does_not_reconcile_with_samples")
    if not math.isclose(observed_window_heater_wh, result["window_open_heater_wh"], abs_tol=0.001):
        errors.append("window_open_energy_does_not_reconcile_with_samples")
    return {
        "valid": not errors,
        "errors": errors,
        "sample_count": len(samples),
        "start_ms": samples[0]["t_ms"],
        "end_ms": samples[-1]["t_ms"],
        "recomputed_heater_energy_wh": round(observed_heater_wh, 4),
        "recorded_heater_energy_wh": result["heater_energy_wh"],
        "recomputed_window_open_heater_wh": round(observed_window_heater_wh, 4),
        "recorded_window_open_heater_wh": result["window_open_heater_wh"],
    }


def run() -> dict:
    manifest_path = ROOT / "revision_drafts" / "20260927" / "HC-PAIR-C2-VENT-HEAT-REVIEW.json"
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    traces = []
    for config in CONFIGS:
        for policy in POLICIES:
            row = simulate(**{key: value for key, value in config.items()
                              if key != "condition"}, policy=policy, record_samples=True)
            traces.append({
                "condition": config["condition"],
                "config": config,
                "policy": policy,
                "result": {key: value for key, value in row.items() if key != "samples"},
                "trace": row["samples"],
                "audit": audit_trace(row),
            })
    payload = {
        "schema_version": "c2-representative-trace-packet-0.1",
        "status": "synthetic_uncalibrated_review_only",
        "independent_scenarios": 2,
        "policy_runs": len(traces),
        "api_calls": 0,
        "physical_device_runs": 0,
        "physics_calibrated": False,
        "scenario_manifest_sha256": manifest_hash,
        "all_trace_invariants_pass": all(item["audit"]["valid"] for item in traces),
        "invariant_definition": [
            "sample clocks strictly advance",
            "CO2 is unchanged while window closed and non-increasing while open",
            "with window open and heater off, indoor temperature does not rise",
            "heater power is either 0 or 2 kW",
            "sample-integrated heater energy reconciles with simulator summary"
        ],
        "traces": traces,
        "limitations": "A self-audit verifies internal consistency of this synthetic implementation only; it does not validate equations or parameters against a real home.",
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({"policy_runs": result["policy_runs"],
                      "all_trace_invariants_pass": result["all_trace_invariants_pass"],
                      "output": str(OUTPUT)}, ensure_ascii=False, indent=2))
