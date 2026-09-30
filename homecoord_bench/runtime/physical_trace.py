"""Input contract and sampled metrics for HC-M06-style physical traces.

This module does not simulate device physics. It validates and scores supplied
sensor/actuator trajectories, retaining provenance so synthetic fixtures cannot
silently become calibrated benchmark evidence.
"""

from __future__ import annotations

import math
from typing import Any


SCHEMA_VERSION = "homecoord-physical-trace-0.1"
SOURCE_KINDS = {"synthetic_fixture", "external_simulator", "physical_device"}
CONDITIONS = {"conflict", "control"}
SAMPLE_FIELDS = ("t_ms", "indoor_temp_c", "outdoor_temp_c", "co2_ppm",
                 "window_open", "heater_power_kw")


def _finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_trace(trace: dict[str, Any]) -> list[str]:
    """Return actionable errors; an empty list means schema-valid, not calibrated."""
    errors: list[str] = []
    if not isinstance(trace, dict):
        return ["trace must be an object"]
    if trace.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be homecoord-physical-trace-0.1")
    if trace.get("sampling_semantics") != "interval_ending_at_t":
        errors.append("sampling_semantics must be interval_ending_at_t")
    if not isinstance(trace.get("trace_id"), str) or not trace["trace_id"].strip():
        errors.append("trace_id must be a nonempty string")
    source = trace.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    if source.get("kind") not in SOURCE_KINDS:
        errors.append("source.kind must identify synthetic_fixture, external_simulator, or physical_device")
    for key in ("revision", "raw_data_reference", "calibration_status", "license_note"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            errors.append(f"source.{key} must be a nonempty string")
    trial = trace.get("trial")
    if not isinstance(trial, dict):
        errors.append("trial must be an object")
        trial = {}
    for key in ("pair_id", "world_config_id", "policy"):
        if not isinstance(trial.get(key), str) or not trial[key].strip():
            errors.append(f"trial.{key} must be a nonempty string")
    if trial.get("condition") not in CONDITIONS:
        errors.append("trial.condition must be conflict or control")
    for key in ("initial_temp_c", "initial_co2_ppm", "outdoor_temp_c",
                "target_temp_c", "target_co2_ppm", "initial_heater_power_kw"):
        if not _finite_number(trial.get(key)):
            errors.append(f"trial.{key} must be a finite number")
    if type(trial.get("initial_window_open")) is not bool:
        errors.append("trial.initial_window_open must be boolean")
    deadline = trial.get("deadline_ms")
    if type(deadline) is not int or deadline <= 0:
        errors.append("trial.deadline_ms must be a positive integer")
    samples = trace.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        errors.append("samples must contain at least two ordered observations")
        return errors
    prev_time: int | None = None
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            errors.append(f"samples[{index}] must be an object")
            continue
        missing = set(SAMPLE_FIELDS) - sample.keys()
        if missing:
            errors.append(f"samples[{index}] missing {sorted(missing)}")
            continue
        t = sample["t_ms"]
        if type(t) is not int or t < 0 or (prev_time is not None and t <= prev_time):
            errors.append(f"samples[{index}].t_ms must strictly increase from zero")
        else:
            prev_time = t
        for key in ("indoor_temp_c", "outdoor_temp_c", "co2_ppm", "heater_power_kw"):
            if not _finite_number(sample[key]):
                errors.append(f"samples[{index}].{key} must be finite numeric")
        if type(sample["window_open"]) is not bool:
            errors.append(f"samples[{index}].window_open must be boolean")
        if _finite_number(sample["heater_power_kw"]) and not 0 <= sample["heater_power_kw"] <= 30:
            errors.append(f"samples[{index}].heater_power_kw outside 0..30 kW")
        if _finite_number(sample["co2_ppm"]) and not 250 <= sample["co2_ppm"] <= 10000:
            errors.append(f"samples[{index}].co2_ppm outside 250..10000 ppm")
        for key in ("indoor_temp_c", "outdoor_temp_c"):
            if _finite_number(sample[key]) and not -50 <= sample[key] <= 70:
                errors.append(f"samples[{index}].{key} outside -50..70 C")
    if errors:
        return errors
    if samples[0].get("t_ms") != 0:
        errors.append("first sample must be at t_ms=0, relative to task release")
    if _finite_number(trial.get("initial_temp_c")) and _finite_number(samples[0].get("indoor_temp_c")):
        if abs(trial["initial_temp_c"] - samples[0]["indoor_temp_c"]) > 0.05:
            errors.append("initial indoor temperature disagrees with first sample")
    if _finite_number(trial.get("initial_co2_ppm")) and _finite_number(samples[0].get("co2_ppm")):
        if abs(trial["initial_co2_ppm"] - samples[0]["co2_ppm"]) > 5:
            errors.append("initial CO2 disagrees with first sample")
    if abs(trial["outdoor_temp_c"] - samples[0]["outdoor_temp_c"]) > 0.05:
        errors.append("initial outdoor temperature disagrees with first sample")
    if trial["initial_window_open"] != samples[0]["window_open"]:
        errors.append("initial window state disagrees with first sample")
    if abs(trial["initial_heater_power_kw"] - samples[0]["heater_power_kw"]) > 0.01:
        errors.append("initial heater power disagrees with first sample")
    if type(deadline) is int and samples[-1]["t_ms"] < deadline:
        goal_already_observed = any(
            sample["indoor_temp_c"] >= trial["target_temp_c"]
            and sample["co2_ppm"] <= trial["target_co2_ppm"]
            and not sample["window_open"] for sample in samples)
        if not goal_already_observed:
            errors.append("trace ends before deadline without observed goal completion")
    events = trace.get("events", [])
    if not isinstance(events, list):
        errors.append("events must be a list when supplied")
    else:
        for index, event in enumerate(events):
            if not isinstance(event, dict) or type(event.get("at_ms")) is not int or not isinstance(event.get("type"), str):
                errors.append(f"events[{index}] requires integer at_ms and string type")
            elif event["at_ms"] < 0 or event["at_ms"] > samples[-1]["t_ms"]:
                errors.append(f"events[{index}].at_ms outside sampled horizon")
    return errors


def score_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Compute observed outcomes; endpoint timing is limited by sample gaps."""
    errors = validate_trace(trace)
    if errors:
        raise ValueError("invalid physical trace: " + "; ".join(errors))
    trial = trace["trial"]
    samples = trace["samples"]
    target_temp = trial["target_temp_c"]
    target_co2 = trial["target_co2_ppm"]
    completion = next((i for i, sample in enumerate(samples)
                       if sample["indoor_temp_c"] >= target_temp
                       and sample["co2_ppm"] <= target_co2
                       and not sample["window_open"]), None)
    completion_ms = samples[completion]["t_ms"] if completion is not None else None
    completion_lower_ms = samples[completion - 1]["t_ms"] if completion is not None and completion > 0 else 0
    energy_wh = 0.0
    window_open_heater_wh = 0.0
    energy_by_deadline_wh = 0.0
    window_open_heater_by_deadline_wh = 0.0
    window_open_heater_ms = 0
    max_sample_gap_ms = 0
    deadline = trial["deadline_ms"]
    for prev, sample in zip(samples, samples[1:]):
        dt = sample["t_ms"] - prev["t_ms"]
        max_sample_gap_ms = max(max_sample_gap_ms, dt)
        interval_energy = sample["heater_power_kw"] * dt / 3600
        energy_wh += interval_energy
        covered_before_deadline_ms = max(0, min(sample["t_ms"], deadline) - prev["t_ms"])
        before_deadline_energy = sample["heater_power_kw"] * covered_before_deadline_ms / 3600
        energy_by_deadline_wh += before_deadline_energy
        if sample["window_open"] and sample["heater_power_kw"] > 0:
            window_open_heater_wh += interval_energy
            window_open_heater_by_deadline_wh += before_deadline_energy
            window_open_heater_ms += dt
    deadline_gap = min(abs(sample["t_ms"] - deadline) for sample in samples)
    early_observed_success = completion_ms is not None and completion_ms <= deadline
    first_observed_response = next((sample["t_ms"] for sample in samples[1:]
                                   if sample["window_open"] or sample["heater_power_kw"] > 0), None)
    return {
        "trace_id": trace["trace_id"], "pair_id": trial["pair_id"],
        "condition": trial["condition"], "policy": trial["policy"],
        "source_kind": trace["source"]["kind"],
        "calibration_status": trace["source"]["calibration_status"],
        "observed_goal_completion_ms": completion_ms,
        "goal_completion_observation_interval_ms": [completion_lower_ms, completion_ms] if completion_ms is not None else None,
        "sampled_deadline_met": early_observed_success,
        "first_observed_physical_response_ms": first_observed_response,
        "heater_energy_wh": round(energy_wh, 4),
        "heater_energy_by_deadline_wh": round(energy_by_deadline_wh, 4) if samples[-1]["t_ms"] >= deadline else None,
        "window_open_heater_wh": round(window_open_heater_wh, 4),
        "window_open_heater_by_deadline_wh": round(window_open_heater_by_deadline_wh, 4) if samples[-1]["t_ms"] >= deadline else None,
        "window_open_heater_ms": window_open_heater_ms,
        "max_sample_gap_ms": max_sample_gap_ms,
        "nearest_deadline_sample_gap_ms": deadline_gap,
        "time_resolution_warning": max_sample_gap_ms > 5000 or (not early_observed_success and deadline_gap > 5000),
    }


def validate_matched_pair(conflict: dict[str, Any], control: dict[str, Any]) -> list[str]:
    """Check that paired inputs differ only in initial CO2 among declared setup."""
    errors = [f"conflict: {e}" for e in validate_trace(conflict)]
    errors += [f"control: {e}" for e in validate_trace(control)]
    if errors:
        return errors
    a, b = conflict["trial"], control["trial"]
    if (a["condition"], b["condition"]) != ("conflict", "control"):
        errors.append("pair order must be conflict then control")
    for key in ("pair_id", "world_config_id", "policy", "initial_temp_c",
                "outdoor_temp_c", "initial_window_open", "initial_heater_power_kw",
                "target_temp_c", "target_co2_ppm", "deadline_ms"):
        if a[key] != b[key]:
            errors.append(f"pair differs in trial.{key}")
    for key in ("kind", "revision", "calibration_status", "license_note"):
        if conflict["source"][key] != control["source"][key]:
            errors.append(f"pair has different source.{key}")
    if not (a["initial_co2_ppm"] > a["target_co2_ppm"]
            and b["initial_co2_ppm"] <= b["target_co2_ppm"]):
        errors.append("pair must cross the initial CO2 target boundary")
    return errors
