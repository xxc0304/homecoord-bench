"""Check whether the current synthetic C2 rates match measured trace scale.

This is an observational compatibility audit, not causal parameter fitting.
Window opening and heater operation were not randomized, and the indoor
environment columns were interpolated from five-minute measurements.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parent
DERIVED = ROOT / "data" / "derived_public"
OUTPUT = ROOT / "results" / "c2_observational_compatibility_20260928.json"

CURRENT_HEAT_RATE_C_PER_S = 0.025
CURRENT_EXCHANGE_PER_S = 0.0015
CURRENT_VENTILATION_RATES_PPM_S = (2.5, 5.0)
CO2_TARGET_PPM = 900.0

TRACE_PATHS = (
    DERIVED / "figshare_pre_retrofit_unit1_event_trace.json",
    DERIVED / "figshare_pre_retrofit_unit2_event_trace.json",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _consecutive_open_samples(window: dict[str, Any]) -> list[dict[str, Any]]:
    field = window["event"]["state_field"]
    samples = [sample for sample in window["samples"] if sample["minutes_from_transition"] >= 0]
    selected: list[dict[str, Any]] = []
    for sample in samples:
        if sample["window_door_states"].get(field) != 1:
            break
        if sample["living_room_baseboard_power_kw"] is None:
            break
        selected.append(sample)
        if len(selected) == 6:
            break
    return selected


def _event_row(trace: dict[str, Any], window: dict[str, Any], index: int) -> dict[str, Any]:
    event = window["event"]
    open_samples = _consecutive_open_samples(window)
    row: dict[str, Any] = {
        "file_id": trace["source"]["file_id"],
        "file_name": trace["source"]["file_name"],
        "event_index": index,
        "event_timestamp": event["event_timestamp_minute_bin"],
        "state_field": event["state_field"],
        "initial_co2_ppm": event["pre_event_5min_mean_co2_ppm"],
        "initial_indoor_temp_c": event["pre_event_5min_mean_indoor_temp_c"],
        "outdoor_temp_c": event["outdoor_temp_c_at_event_minute"],
        "heater_power_kw": event["baseboard_power_kw_at_event_minute"],
        "consecutive_open_observed_bins": len(open_samples),
        "benchmark_like_high_co2": (
            event["pre_event_5min_mean_co2_ppm"] is not None
            and event["pre_event_5min_mean_co2_ppm"] > CO2_TARGET_PPM
        ),
        "usable_for_net_slope": False,
    }
    if len(open_samples) < 2:
        row["exclusion_reason"] = "fewer than two consecutive open-window minute bins"
        return row

    first, last = open_samples[0], open_samples[-1]
    minutes = last["minutes_from_transition"] - first["minutes_from_transition"]
    required = (first["indoor_temp_c"], last["indoor_temp_c"],
                first["co2_ppm"], last["co2_ppm"], first["outdoor_temp_c"])
    if minutes <= 0 or any(value is None for value in required):
        row["exclusion_reason"] = "missing environmental value or zero observation horizon"
        return row

    seconds = minutes * 60.0
    temp_rate = (last["indoor_temp_c"] - first["indoor_temp_c"]) / seconds
    co2_rate = (last["co2_ppm"] - first["co2_ppm"]) / seconds
    delta_t = first["indoor_temp_c"] - first["outdoor_temp_c"]
    implied_exchange = (
        (CURRENT_HEAT_RATE_C_PER_S - temp_rate) / delta_t if delta_t > 0 else None
    )
    implied_heat_rate = temp_rate + CURRENT_EXCHANGE_PER_S * max(delta_t, 0.0)
    predicted_temp_rate = CURRENT_HEAT_RATE_C_PER_S - CURRENT_EXCHANGE_PER_S * max(delta_t, 0.0)

    row.update({
        "usable_for_net_slope": True,
        "observation_horizon_minutes": minutes,
        "observed_net_temp_rate_c_per_s": round(temp_rate, 8),
        "observed_net_co2_rate_ppm_per_s": round(co2_rate, 8),
        "current_model_net_temp_rate_c_per_s_at_initial_state": round(predicted_temp_rate, 8),
        "implied_exchange_per_s_if_heat_rate_fixed_at_0_025": (
            round(implied_exchange, 8) if implied_exchange is not None else None
        ),
        "implied_heat_rate_c_per_s_if_exchange_fixed_at_0_0015": round(implied_heat_rate, 8),
        "co2_rate_inside_current_synthetic_range": (
            -max(CURRENT_VENTILATION_RATES_PPM_S) <= co2_rate
            <= -min(CURRENT_VENTILATION_RATES_PPM_S)
        ),
    })
    return row


def run(output: Path = OUTPUT) -> dict[str, Any]:
    traces = [_load(path) for path in TRACE_PATHS]
    rows = [
        _event_row(trace, window, index)
        for trace in traces
        for index, window in enumerate(trace["selected_event_windows"], start=1)
    ]
    usable = [row for row in rows if row["usable_for_net_slope"]]
    high_co2 = [row for row in usable if row["benchmark_like_high_co2"]]
    result = {
        "experiment": "c2_observational_compatibility_audit",
        "status": "observational_scale_check_not_causal_calibration",
        "current_synthetic_parameters": {
            "heat_rate_c_per_s": CURRENT_HEAT_RATE_C_PER_S,
            "open_exchange_per_s": CURRENT_EXCHANGE_PER_S,
            "ventilation_rates_ppm_s": list(CURRENT_VENTILATION_RATES_PPM_S),
            "co2_target_ppm": CO2_TARGET_PPM,
        },
        "summary": {
            "independent_units": len(traces),
            "selected_windows": len(rows),
            "usable_multi_bin_open_windows": len(usable),
            "usable_high_co2_windows": len(high_co2),
            "high_co2_windows_by_file": {
                trace["source"]["file_id"]: sum(
                    row["file_id"] == trace["source"]["file_id"]
                    and row["benchmark_like_high_co2"] for row in usable
                )
                for trace in traces
            },
            "co2_rates_inside_current_synthetic_range": sum(
                row["co2_rate_inside_current_synthetic_range"] for row in high_co2
            ),
            "median_observed_net_temp_rate_c_per_s": (
                round(median(row["observed_net_temp_rate_c_per_s"] for row in usable), 8)
                if usable else None
            ),
            "median_observed_net_co2_rate_ppm_per_s_high_co2": (
                round(median(row["observed_net_co2_rate_ppm_per_s"] for row in high_co2), 8)
                if high_co2 else None
            ),
            "decision": (
                "Do not promote the current C2 dynamics to calibrated status. "
                "The traces constrain joint net trajectories only; separate causal window and heater "
                "effects remain unidentifiable without interventions or a validated simulator."
            ),
        },
        "rows": rows,
        "limitations": [
            "Window opening and heating are observational rather than randomized interventions.",
            "Indoor temperature and CO2 minute values were interpolated from five-minute samples.",
            "The heater circuit can aggregate loads and its power does not identify delivered room heat.",
            "A net temperature slope cannot uniquely identify both heater gain and window heat loss.",
            "Selected windows are examples from two units, not independent population samples.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    report = run()
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote: {OUTPUT}")


if __name__ == "__main__":
    main()
