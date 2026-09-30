"""Exploratory HC-M07 pilot with persistent window state and gradual effects.

This does not modify the candidate episode or claim calibrated device physics.
The same ventilation and cooling requests are replayed under four simple
coordination policies. A new close-window step makes the global goal feasible.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from evaluate import ROOT, load_json
from run_protocol_pilot import INSTRUCTIONS
from runtime.dry_run import DryRunClient
from runtime.execution import run_closed_loop_episode


STEP_MS = 100
OPEN_AT_MS = 700
OPEN_ACTION_END_MS = 2700
COOL_READY_MS = 800
CLOSE_ACTUATION_MS = 300
CO2_TARGET_PPM = 900
TEMP_TARGET_C = 24.0
COOLING_DEADLINE_MS = 10000
COOLING_RATE_C_PER_S_CLOSED = 2.0
COOLING_RATE_C_PER_S_OPEN = 0.5
POLICIES = ("Independent", "ActionOverlapLock", "StateGate", "FullSequence")


def simulate(initial_co2_ppm: int, co2_drop_ppm_per_s: int, policy: str) -> dict:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    if co2_drop_ppm_per_s <= 0:
        raise ValueError("CO2 decrease rate must be positive")

    co2 = float(initial_co2_ppm)
    temperature = 30.0
    ventilation_needed = co2 > CO2_TARGET_PPM
    steps_to_target = math.ceil(
        (co2 - CO2_TARGET_PPM) / (co2_drop_ppm_per_s * STEP_MS / 1000) - 1e-9
    ) if ventilation_needed else 0
    planned_cooling_start_ms = (
        OPEN_AT_MS + steps_to_target * STEP_MS + CLOSE_ACTUATION_MS
        if ventilation_needed else COOL_READY_MS
    )
    window_open = False
    cooling_on = False
    cooling_started = False
    close_effect_ms = None
    cooling_start_ms = None
    goal_completion_ms = None
    open_window_cooling_ms = 0
    events = []

    for now in range(0, 20001, STEP_MS):
        if ventilation_needed and now == OPEN_AT_MS:
            window_open = True
            events.append({"at_ms": now, "type": "window_opened", "agent": "AirQualityAgent"})
        if close_effect_ms is not None and now == close_effect_ms:
            window_open = False
            events.append({"at_ms": now, "type": "window_closed", "agent": "AirQualityAgent"})

        if not cooling_started and now >= COOL_READY_MS:
            if policy == "Independent":
                may_start = True
            elif policy == "ActionOverlapLock":
                may_start = not ventilation_needed or now >= OPEN_ACTION_END_MS
            elif policy == "StateGate":
                may_start = not window_open and co2 <= CO2_TARGET_PPM
            else:
                # Full-information temporal plan knows the synthetic CO2 rate.
                may_start = now >= planned_cooling_start_ms
            if may_start:
                cooling_started = cooling_on = True
                cooling_start_ms = now
                events.append({"at_ms": now, "type": "cooling_started", "agent": "CoolingAgent"})

        if window_open:
            co2 = max(CO2_TARGET_PPM, co2 - co2_drop_ppm_per_s * STEP_MS / 1000)
            if cooling_on:
                open_window_cooling_ms += STEP_MS
        if cooling_on:
            rate = COOLING_RATE_C_PER_S_OPEN if window_open else COOLING_RATE_C_PER_S_CLOSED
            temperature = max(TEMP_TARGET_C, temperature - rate * STEP_MS / 1000)
            if temperature <= TEMP_TARGET_C + 1e-9:
                cooling_on = False
                events.append({"at_ms": now + STEP_MS, "type": "cooling_target_reached", "agent": "CoolingAgent"})

        if window_open and co2 <= CO2_TARGET_PPM and close_effect_ms is None:
            close_effect_ms = now + STEP_MS + CLOSE_ACTUATION_MS
            events.append({"at_ms": now + STEP_MS, "type": "close_window_command", "agent": "AirQualityAgent"})
        if (goal_completion_ms is None and not window_open and co2 <= CO2_TARGET_PPM
                and temperature <= TEMP_TARGET_C + 1e-9):
            goal_completion_ms = now + STEP_MS
            break

    return {
        "initial_co2_ppm": initial_co2_ppm,
        "co2_drop_ppm_per_s": co2_drop_ppm_per_s,
        "policy": policy,
        "window_close_ms": close_effect_ms,
        "planned_cooling_start_ms": planned_cooling_start_ms if policy == "FullSequence" else None,
        "cooling_start_ms": cooling_start_ms,
        "goal_completion_ms": goal_completion_ms,
        "open_window_cooling_ms": open_window_cooling_ms,
        "state_invariant_valid": open_window_cooling_ms == 0,
        "deadline_met": goal_completion_ms is not None and goal_completion_ms <= COOLING_DEADLINE_MS,
        "valid_on_time": open_window_cooling_ms == 0 and goal_completion_ms is not None
        and goal_completion_ms <= COOLING_DEADLINE_MS,
        "final_co2_ppm": round(co2, 1),
        "final_temperature_c": round(temperature, 2),
        "events": events,
    }


def run(output_path: Path) -> dict:
    source = load_json(ROOT / "data" / "candidates" / "HC-M07.json")
    legacy_trace, legacy_result = run_closed_loop_episode(
        source, DryRunClient(), "ConstraintCoordinator", INSTRUCTIONS, synthetic_latency=True
    )
    legacy_actions = [
        {"at_ms": event["timestamp_ms"], "target": event["target"],
         "operation": event["operation"], "duration_ms": event["duration_ms"]}
        for event in legacy_trace["events"] if event["type"] == "action_effective"
    ]
    cooling_time = next(action["at_ms"] for action in legacy_actions if action["target"] == "living_hvac")
    window_state_at_cooling = source["initial_state"]["values"]["devices"]["window"]
    for event in legacy_trace["events"]:
        if event["type"] == "action_effective" and event["timestamp_ms"] <= cooling_time:
            window_state_at_cooling = event.get("effects", {}).get("devices.window", window_state_at_cooling)
    rows = [
        simulate(initial_co2, drop_rate, policy)
        for initial_co2, drop_rate in [(850, 150), (1600, 100), (1600, 150), (1600, 300)]
        for policy in POLICIES
    ]
    summary = {
        policy: {
            "cases": 4,
            "state_invariant_valid": sum(row["state_invariant_valid"] for row in rows if row["policy"] == policy),
            "valid_on_time": sum(row["valid_on_time"] for row in rows if row["policy"] == policy),
            "completion_by_deadline": sum(row["deadline_met"] for row in rows if row["policy"] == policy),
        }
        for policy in POLICIES
    }
    payload = {
        "experiment": "persistent_state_hc_m07_design_pilot",
        "status": "synthetic_unreviewed_design_experiment",
        "source_episode": source["episode_id"],
        "legacy": {"process_valid_success": legacy_result["process_valid_success"],
                   "conflict_counts": legacy_result["conflict_counts"],
                   "window_state_at_cooling_start": window_state_at_cooling,
                   "actions": legacy_actions},
        "assumptions": {
            "open_action_start_ms": OPEN_AT_MS,
            "open_action_end_ms": OPEN_ACTION_END_MS,
            "cooling_ready_ms": COOL_READY_MS,
            "close_actuation_ms": CLOSE_ACTUATION_MS,
            "co2_target_ppm": CO2_TARGET_PPM,
            "temperature_target_c": TEMP_TARGET_C,
            "cooling_deadline_ms": COOLING_DEADLINE_MS,
            "cooling_rate_closed_c_per_s": COOLING_RATE_C_PER_S_CLOSED,
            "cooling_rate_open_c_per_s": COOLING_RATE_C_PER_S_OPEN,
        },
        "limitations": "Synthetic rates and deadline; the old episode has instant effects and no close action. New rules are only a pilot, not integrated into the benchmark evaluator.",
        "summary": summary,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "persistent_state_pilot_20260924.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))
