"""Uncalibrated HC-M06 design probe: ventilation and heating share room physics.

This deliberately does not reuse HC-M06's instant ``effects`` or modify its
candidate JSON. It asks whether avoiding simultaneous commands is sufficient
once an opened window keeps affecting the room until it is physically closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT, load_json


STEP_MS = 1000
OPEN_AT_MS = 7000
OPEN_COMMAND_END_MS = 9000
HEAT_READY_MS = 8000
CLOSE_DELAY_MS = 3000
INITIAL_TEMP_C = 17.0
OUTDOOR_TEMP_C = 8.0
TARGET_TEMP_C = 21.0
TARGET_CO2_PPM = 900.0
HEAT_RATE_C_PER_S = 0.025
HEATER_POWER_KW = 2.0
POLICIES = ("Independent", "DeviceLock", "ActionOverlapLock", "StateGate", "OracleSwitch")


def simulate(*, initial_co2_ppm: int, ventilation_rate_ppm_s: float,
             open_exchange_per_s: float, deadline_ms: int, policy: str,
             record_samples: bool = False,
             air_proposal_ready_ms: int | None = None,
             heat_proposal_ready_ms: int | None = None,
             air_action_proposed: bool = True,
             heat_action_proposed: bool = True,
             heat_rate_c_per_s: float = HEAT_RATE_C_PER_S) -> dict:
    if policy not in POLICIES:
        raise ValueError(policy)
    if ventilation_rate_ppm_s <= 0 or open_exchange_per_s < 0 or heat_rate_c_per_s <= 0:
        raise ValueError("rates must be nonnegative; ventilation must be positive")
    if policy == "OracleSwitch":
        # Reference upper bound: knows the exact synthetic dynamics and deadline.
        args = dict(initial_co2_ppm=initial_co2_ppm,
                    ventilation_rate_ppm_s=ventilation_rate_ppm_s,
                    open_exchange_per_s=open_exchange_per_s, deadline_ms=deadline_ms,
                    air_proposal_ready_ms=air_proposal_ready_ms,
                    heat_proposal_ready_ms=heat_proposal_ready_ms,
                    air_action_proposed=air_action_proposed,
                    heat_action_proposed=heat_action_proposed,
                    heat_rate_c_per_s=heat_rate_c_per_s)
        gate = simulate(**args, policy="StateGate")
        selected = "StateGate" if gate["deadline_met"] else "Independent"
        chosen = simulate(**args, policy=selected, record_samples=record_samples)
        return {**chosen, "policy": "OracleSwitch", "selected_policy": selected}
    needs_ventilation = initial_co2_ppm > TARGET_CO2_PPM
    # Historical calls are sampled sequentially, but their elapsed times are
    # replayed as logical asynchronous arrivals from the respective releases.
    # Round to this simulator's one-second physical tick; do not imply finer
    # physical timing precision than the environment actually supports.
    def tick_at_or_after(at_ms: int) -> int:
        return ((at_ms + STEP_MS - 1) // STEP_MS) * STEP_MS

    open_at_ms = tick_at_or_after(max(OPEN_AT_MS, air_proposal_ready_ms or OPEN_AT_MS))
    heater_ready_ms = tick_at_or_after(max(HEAT_READY_MS, heat_proposal_ready_ms or HEAT_READY_MS))
    will_ventilate = needs_ventilation and air_action_proposed
    # Optimistic service lower bound: ventilation must first lower CO2 and the
    # window must close; heating needs its own minimum run time. Heat loss is
    # ignored, so a bound above the deadline proves infeasibility, while a
    # bound below it does not guarantee physical feasibility.
    vent_finish_lower_bound_ms = (
        open_at_ms + (initial_co2_ppm - TARGET_CO2_PPM) / ventilation_rate_ppm_s * 1000
        + CLOSE_DELAY_MS if needs_ventilation else 0
    )
    heat_finish_lower_bound_ms = heater_ready_ms + (TARGET_TEMP_C - INITIAL_TEMP_C) / heat_rate_c_per_s * 1000
    optimistic_completion_lower_bound_ms = max(vent_finish_lower_bound_ms,
                                               heat_finish_lower_bound_ms)
    co2 = float(initial_co2_ppm)
    temp = INITIAL_TEMP_C
    window_open = False
    close_at_ms = None
    heater_enabled = False
    heater_first_start_ms = None
    heater_on_ms = 0
    window_open_heater_ms = 0
    heat_loss_degree_seconds = 0.0
    goal_completion_ms = None
    events = []
    # Sample power/window values describe the interval ending at t_ms.
    samples = [{"t_ms": 0, "indoor_temp_c": temp,
                "outdoor_temp_c": OUTDOOR_TEMP_C, "co2_ppm": co2,
                "window_open": False, "heater_power_kw": 0.0}] if record_samples else None

    for now in range(0, 900001, STEP_MS):
        if will_ventilate and now == open_at_ms:
            window_open = True
            events.append({"at_ms": now, "type": "window_opened"})
        if close_at_ms is not None and now == close_at_ms:
            window_open = False
            events.append({"at_ms": now, "type": "window_closed"})

        if heat_action_proposed and not heater_enabled and now >= heater_ready_ms:
            if policy in ("Independent", "DeviceLock"):
                may_start = True  # the two requests write different devices
            elif policy == "ActionOverlapLock":
                may_start = not will_ventilate or now >= open_at_ms + (OPEN_COMMAND_END_MS - OPEN_AT_MS)
            else:
                may_start = not window_open and co2 <= TARGET_CO2_PPM
            if may_start:
                heater_enabled = True
                heater_first_start_ms = now
                events.append({"at_ms": now, "type": "heater_enabled"})

        dt_s = STEP_MS / 1000
        if window_open:
            co2 = max(TARGET_CO2_PPM, co2 - ventilation_rate_ppm_s * dt_s)
            loss_rate = open_exchange_per_s * max(temp - OUTDOOR_TEMP_C, 0.0)
            heat_loss_degree_seconds += loss_rate * dt_s
            temp -= loss_rate * dt_s
        heater_running = False
        if heater_enabled and temp < TARGET_TEMP_C - 1e-9:
            heater_running = True
            heater_on_ms += STEP_MS
            if window_open:
                window_open_heater_ms += STEP_MS
            temp = min(TARGET_TEMP_C, temp + heat_rate_c_per_s * dt_s)
        if samples is not None:
            samples.append({"t_ms": now + STEP_MS,
                            "indoor_temp_c": round(temp, 6),
                            "outdoor_temp_c": OUTDOOR_TEMP_C,
                            "co2_ppm": round(co2, 6),
                            "window_open": window_open,
                            "heater_power_kw": HEATER_POWER_KW if heater_running else 0.0})

        if window_open and co2 <= TARGET_CO2_PPM and close_at_ms is None:
            close_at_ms = now + STEP_MS + CLOSE_DELAY_MS
            events.append({"at_ms": now + STEP_MS, "type": "close_window_command"})
        if (goal_completion_ms is None and not window_open and co2 <= TARGET_CO2_PPM
                and temp >= TARGET_TEMP_C - 1e-9):
            goal_completion_ms = now + STEP_MS
        # Exported sensor traces continue to the deadline even after early
        # success, so energy is observed over a common evaluation horizon.
        if goal_completion_ms is not None and (not record_samples or now + STEP_MS >= deadline_ms):
            break

    result = {
        "initial_co2_ppm": initial_co2_ppm,
        "ventilation_rate_ppm_s": ventilation_rate_ppm_s,
        "open_exchange_per_s": open_exchange_per_s,
        "deadline_ms": deadline_ms,
        "air_proposal_ready_ms": air_proposal_ready_ms,
        "heat_proposal_ready_ms": heat_proposal_ready_ms,
        "air_action_proposed": air_action_proposed,
        "heat_action_proposed": heat_action_proposed,
        "heat_rate_c_per_s": heat_rate_c_per_s,
        "window_open_command_ms": open_at_ms if will_ventilate else None,
        "optimistic_completion_lower_bound_ms": round(optimistic_completion_lower_bound_ms),
        "deadline_not_ruled_out_by_lower_bound": optimistic_completion_lower_bound_ms <= deadline_ms,
        "policy": policy,
        "window_close_ms": close_at_ms,
        "heater_first_start_ms": heater_first_start_ms,
        "goal_completion_ms": goal_completion_ms,
        "deadline_met": goal_completion_ms is not None and goal_completion_ms <= deadline_ms,
        "heater_on_ms": heater_on_ms,
        "heater_energy_wh": round(HEATER_POWER_KW * heater_on_ms / 3600, 4),
        "window_open_heater_ms": window_open_heater_ms,
        "window_open_heater_wh": round(HEATER_POWER_KW * window_open_heater_ms / 3600, 4),
        "gross_ventilation_heat_loss_degree_seconds": round(heat_loss_degree_seconds, 4),
        "final_temp_c": round(temp, 3),
        "final_co2_ppm": round(co2, 1),
        "events": events,
    }
    if samples is not None:
        result["samples"] = samples
    return result


def run(output_path: Path) -> dict:
    source = load_json(ROOT / "data" / "candidates" / "HC-M06.json")
    cases = [(co2, rate, exchange, deadline)
             for co2 in (850, 1600)
             for rate in (2.5, 5.0)
             for exchange in (0.0005, 0.0015, 0.003)
             for deadline in (240000, 360000, 480000)]
    rows = [simulate(initial_co2_ppm=co2, ventilation_rate_ppm_s=rate,
                     open_exchange_per_s=exchange, deadline_ms=deadline,
                     policy=policy)
            for co2, rate, exchange, deadline in cases for policy in POLICIES]
    summary = {}
    for policy in POLICIES:
        subset = [row for row in rows if row["policy"] == policy]
        summary[policy] = {
            "cases": len(subset),
            "deadline_met": sum(row["deadline_met"] for row in subset),
            "total_heater_wh": round(sum(row["heater_energy_wh"] for row in subset), 3),
            "total_window_open_heater_wh": round(sum(row["window_open_heater_wh"] for row in subset), 3),
        }
    paired = []
    for co2, rate, exchange, deadline in cases:
        subset = [row for row in rows if (row["initial_co2_ppm"],
                  row["ventilation_rate_ppm_s"], row["open_exchange_per_s"],
                  row["deadline_ms"]) == (co2, rate, exchange, deadline)]
        by_policy = {row["policy"]: row for row in subset}
        independent, gate = by_policy["Independent"], by_policy["StateGate"]
        paired.append({"initial_co2_ppm": co2, "ventilation_rate_ppm_s": rate,
                       "open_exchange_per_s": exchange, "deadline_ms": deadline,
                       "independent_meets_gate_misses": independent["deadline_met"] and not gate["deadline_met"],
                       "gate_saves_energy_wh": round(independent["heater_energy_wh"] - gate["heater_energy_wh"], 4)})
    conflict_pairs = [row for row in paired if row["initial_co2_ppm"] > TARGET_CO2_PPM]
    control_pairs = [row for row in paired if row["initial_co2_ppm"] <= TARGET_CO2_PPM]
    paired_summary = {
        "conflict_grid_cells": len(conflict_pairs),
        "matched_control_grid_cells": len(control_pairs),
        "conflict_independent_on_time_gate_miss": sum(
            row["independent_meets_gate_misses"] for row in conflict_pairs),
        "control_independent_on_time_gate_miss": sum(
            row["independent_meets_gate_misses"] for row in control_pairs),
        "conflict_gate_saves_energy_positive": sum(
            row["gate_saves_energy_wh"] > 0 for row in conflict_pairs),
        "control_gate_saves_energy_positive": sum(
            row["gate_saves_energy_wh"] > 0 for row in control_pairs),
    }
    feasibility_strata = {}
    for name, predicate in (
        ("conflict", lambda row: row["initial_co2_ppm"] > TARGET_CO2_PPM),
        ("matched_control", lambda row: row["initial_co2_ppm"] <= TARGET_CO2_PPM),
    ):
        subset = [row for row in rows if predicate(row)]
        by_cell: dict[tuple, dict[str, dict]] = {}
        for row in subset:
            key = (row["initial_co2_ppm"], row["ventilation_rate_ppm_s"],
                   row["open_exchange_per_s"], row["deadline_ms"])
            by_cell.setdefault(key, {})[row["policy"]] = row
        feasible_keys = [key for key, policies in by_cell.items()
                         if next(iter(policies.values()))["deadline_not_ruled_out_by_lower_bound"]]
        feasibility_strata[name] = {
            "total_grid_cells": len(by_cell),
            "lower_bound_infeasible_cells": len(by_cell) - len(feasible_keys),
            "lower_bound_feasible_cells": len(feasible_keys),
            "note": "The optimistic lower bound ignores heat loss. Above-deadline cells are provably infeasible; below-deadline cells are only not ruled out.",
            "by_policy_on_lower_bound_feasible_cells": {
                policy: {
                    "deadline_met": sum(by_cell[key][policy]["deadline_met"] for key in feasible_keys),
                    "cells": len(feasible_keys),
                    "heater_energy_wh_mean": round(sum(by_cell[key][policy]["heater_energy_wh"]
                                                        for key in feasible_keys) / len(feasible_keys), 4)
                    if feasible_keys else None,
                }
                for policy in POLICIES
            },
        }
    feasible_conflict_keys = {
        (row["initial_co2_ppm"], row["ventilation_rate_ppm_s"],
         row["open_exchange_per_s"], row["deadline_ms"])
        for row in rows if row["initial_co2_ppm"] > TARGET_CO2_PPM
        and row["deadline_not_ruled_out_by_lower_bound"]
    }
    feasibility_strata["conflict"]["independent_on_time_gate_misses_among_feasible"] = sum(
        row["initial_co2_ppm"] > TARGET_CO2_PPM
        and (row["initial_co2_ppm"], row["ventilation_rate_ppm_s"],
             row["open_exchange_per_s"], row["deadline_ms"]) in feasible_conflict_keys
        and row["independent_meets_gate_misses"] for row in paired
    )
    payload = {
        "experiment": "hc_m06_ventilation_heating_design_probe",
        "status": "synthetic_unreviewed_design_experiment",
        "source_episode": source["episode_id"],
        "assumptions": {"step_ms": STEP_MS, "open_at_ms": OPEN_AT_MS,
                        "open_command_end_ms": OPEN_COMMAND_END_MS,
                        "heater_ready_ms": HEAT_READY_MS,
                        "close_delay_ms": CLOSE_DELAY_MS,
                        "initial_temp_c": INITIAL_TEMP_C,
                        "outdoor_temp_c": OUTDOOR_TEMP_C,
                        "target_temp_c": TARGET_TEMP_C,
                        "target_co2_ppm": TARGET_CO2_PPM,
                        "heat_rate_c_per_s": HEAT_RATE_C_PER_S,
                        "heater_power_kw": HEATER_POWER_KW},
        "limitations": "Standalone synthetic room model with uncalibrated rates and deadlines; no model API or real device. Heating target is an endpoint, not a hard safety rule; window-open heating is not automatically invalid. StateGate has direct physical-state access; OracleSwitch additionally knows exact dynamics and is an unfair reference upper bound. Repeated deadline rows share the same physical run and are not independent samples. This is not benchmark runtime evidence or a validated method gap.",
        "summary": summary,
        "paired_summary": paired_summary,
        "optimistic_feasibility_strata": feasibility_strata,
        "paired_tradeoffs": paired,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "ventilation_heating_tradeoff_20260927.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))
