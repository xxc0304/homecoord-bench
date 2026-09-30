"""Dynamic HC-M07 design pilot: rain interrupts ventilation.

All baselines share the same physical dynamics and a 500 ms recovery decision
delay. Planning-scope counts are structural proxies, not measured LLM latency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT


STEP_MS = 100
RAIN_CLOSE_MS = 300
REPAIR_DECISION_MS = 500
DEADLINE_MS = 10000
POLICIES = ("StateGate", "ReactiveFallback", "GlobalReplanTemplate", "LocalRepairTemplate")
SCENARIOS = (
    ("no_event", None, None),
    ("unrelated_event", None, 3000),
    ("rain_before_start", 0, None),
    ("rain_early", 1500, None),
    ("rain_mid", 3000, None),
    ("rain_near_target", 5000, None),
    ("rain_after_ventilation", 6500, None),
)


def simulate(scenario: str, rain_at_ms: int | None, unrelated_at_ms: int | None, policy: str) -> dict:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    co2 = 1600.0
    temperature = 30.0
    window_open = False
    rain_active = False
    purifier_on = False
    cooling_on = False
    cleaned = False
    close_effect_ms = None
    purifier_start_ms = None
    repair_scope_count = 0
    cooling_start_ms = None
    goal_completion_ms = None
    cooling_while_open_ms = 0
    rain_window_exposure_ms = 0
    events = []

    for now in range(0, 20001, STEP_MS):
        if now == 500:
            events.append({"at_ms": now, "type": "cleaning_started", "agent": "CleaningAgent"})
        if now == 6500:
            cleaned = True
            events.append({"at_ms": now, "type": "cleaning_completed", "agent": "CleaningAgent"})
        if unrelated_at_ms is not None and now == unrelated_at_ms:
            events.append({"at_ms": now, "type": "hallway_sensor_update", "agent": "Environment"})
        if rain_at_ms is not None and now == rain_at_ms:
            rain_active = True
            events.append({"at_ms": now, "type": "rain_started", "agent": "Environment"})
            if window_open:
                close_effect_ms = now + RAIN_CLOSE_MS
                events.append({"at_ms": now, "type": "close_window_command", "agent": "SafetyController"})
            if co2 > 900:
                if policy != "StateGate":
                    purifier_start_ms = now + REPAIR_DECISION_MS
                if policy == "GlobalReplanTemplate":
                    repair_scope_count = 2 + int(now < 6500)  # air, climate, pending cleaning
                elif policy == "LocalRepairTemplate":
                    repair_scope_count = 1  # only air-quality branch; HVAC is already state-gated
        if now == 700 and not rain_active:
            window_open = True
            events.append({"at_ms": now, "type": "window_opened", "agent": "AirQualityAgent"})
        if close_effect_ms is not None and now == close_effect_ms:
            window_open = False
            events.append({"at_ms": now, "type": "window_closed", "agent": "AirQualityAgent"})
        if purifier_start_ms is not None and now == purifier_start_ms and co2 > 900:
            purifier_on = True
            events.append({"at_ms": now, "type": "purifier_started", "agent": "AirQualityAgent"})
        if cooling_start_ms is None and now >= 800 and not window_open:
            cooling_start_ms = now
            cooling_on = True
            events.append({"at_ms": now, "type": "cooling_started", "agent": "ClimateAgent"})

        if window_open:
            co2 = max(900, co2 - 150 * STEP_MS / 1000)
            if rain_active:
                rain_window_exposure_ms += STEP_MS
            if cooling_on:
                cooling_while_open_ms += STEP_MS
        if purifier_on:
            co2 = max(900, co2 - 250 * STEP_MS / 1000)
        if cooling_on:
            temperature = max(24, temperature - 2 * STEP_MS / 1000)
            if temperature <= 24 + 1e-9:
                cooling_on = False
                events.append({"at_ms": now + STEP_MS, "type": "cooling_target_reached", "agent": "ClimateAgent"})
        if purifier_on and co2 <= 900:
            purifier_on = False
            events.append({"at_ms": now + STEP_MS, "type": "purifier_stopped", "agent": "AirQualityAgent"})
        if window_open and co2 <= 900 and close_effect_ms is None:
            close_effect_ms = now + STEP_MS + RAIN_CLOSE_MS
            events.append({"at_ms": now + STEP_MS, "type": "close_window_command", "agent": "AirQualityAgent"})
        if (goal_completion_ms is None and cleaned and not window_open and co2 <= 900
                and temperature <= 24 + 1e-9):
            goal_completion_ms = now + STEP_MS
            break

    process_valid = cooling_while_open_ms == 0 and rain_window_exposure_ms <= RAIN_CLOSE_MS
    return {
        "scenario": scenario,
        "rain_at_ms": rain_at_ms,
        "unrelated_at_ms": unrelated_at_ms,
        "policy": policy,
        "process_valid": process_valid,
        "goal_completion_ms": goal_completion_ms,
        "valid_on_time": process_valid and goal_completion_ms is not None and goal_completion_ms <= DEADLINE_MS,
        "cooling_start_ms": cooling_start_ms,
        "purifier_start_ms": purifier_start_ms,
        "repair_scope_count": repair_scope_count,
        "cooling_while_open_ms": cooling_while_open_ms,
        "rain_window_exposure_ms": rain_window_exposure_ms,
        "final_co2_ppm": round(co2, 1),
        "final_temperature_c": round(temperature, 2),
        "cleaned": cleaned,
        "events": events,
    }


def run(output_path: Path) -> dict:
    rows = [simulate(name, rain, unrelated, policy)
            for name, rain, unrelated in SCENARIOS for policy in POLICIES]
    summary = {
        policy: {
            "cases": len(SCENARIOS),
            "process_valid": sum(row["process_valid"] for row in rows if row["policy"] == policy),
            "valid_on_time": sum(row["valid_on_time"] for row in rows if row["policy"] == policy),
            "rain_cases_completed": sum(row["valid_on_time"] for row in rows
                                        if row["policy"] == policy and row["rain_at_ms"] is not None),
            "total_repair_scope_count": sum(row["repair_scope_count"] for row in rows if row["policy"] == policy),
        }
        for policy in POLICIES
    }
    payload = {
        "experiment": "dynamic_partial_repair_hc_m07_design_pilot",
        "status": "synthetic_unreviewed_design_experiment",
        "assumptions": {
            "co2_drop_open_ppm_per_s": 150, "co2_drop_purifier_ppm_per_s": 250,
            "cooling_rate_c_per_s": 2, "rain_window_close_ms": RAIN_CLOSE_MS,
            "repair_decision_ms_all_fallbacks": REPAIR_DECISION_MS,
            "completion_deadline_ms": DEADLINE_MS,
            "note": "SafetyController closes the window on rain for every policy. Both replan templates preserve ongoing cleaning and state-gated cooling. ReactiveFallback has an explicit rain-to-purifier rule.",
        },
        "limitations": "GlobalReplanTemplate and LocalRepairTemplate are scripted idealized execution templates, not implemented planners. No model API, real-device dynamics, measured planning latency, or general task synthesis. Repair scope counts are structural proxies, not timing.",
        "summary": summary,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "dynamic_repair_pilot_20260924.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))
