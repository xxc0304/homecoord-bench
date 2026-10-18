"""M04: one joint synthetic CO2/temperature/power simulation.

This deliberately evaluates the coupled trajectory in one clock. It does not
paste together two independent C2 and C3 scores. Rates remain uncalibrated.
"""

from __future__ import annotations

import json

from evaluate import ROOT

OUT = ROOT / "results" / "m04_joint_environment_synthetic_20260928.json"
POLICIES = ("water_first", "climate_first", "avoid_window_overlap")
STEP_MS = 1000


def simulate(initial_co2: float, capacity_kw: float, policy: str) -> dict:
    if policy not in POLICIES or initial_co2 < 400 or capacity_kw <= 0:
        raise ValueError((initial_co2, capacity_kw, policy))
    co2, temp = float(initial_co2), 17.0
    window_open = False
    close_at = None
    water_remaining_kws = 180.0  # 1.5 kW x 120 s, synthetic
    water_completed_ms = heat_completed_ms = vent_completed_ms = None
    heater_energy_wh = window_heat_ms = 0.0
    maximum_load = 0.0
    trace = []
    for now in range(0, 601_000, STEP_MS):
        if now == 7000 and co2 > 900:
            window_open = True
            trace.append((now, "window_open"))
        if close_at == now:
            window_open = False
            vent_completed_ms = now
            trace.append((now, "window_close_ack"))
        if co2 <= 900 and not window_open and vent_completed_ms is None:
            vent_completed_ms = 0
        water_needed = water_remaining_kws > 1e-9 and now >= 8000
        heat_needed = temp < 21.0 - 1e-9 and now >= 8000
        if policy == "avoid_window_overlap" and window_open:
            heat_needed = False
        water_on = heat_on = False
        if policy == "climate_first":
            if heat_needed and 2.0 <= capacity_kw:
                heat_on = True
            if water_needed and 1.5 + (2.0 if heat_on else 0.0) <= capacity_kw:
                water_on = True
        else:
            if water_needed and 1.5 <= capacity_kw:
                water_on = True
            if heat_needed and 2.0 + (1.5 if water_on else 0.0) <= capacity_kw:
                heat_on = True
        load = (1.5 if water_on else 0.0) + (2.0 if heat_on else 0.0)
        if load > capacity_kw + 1e-9:
            raise AssertionError("joint resource limit exceeded")
        maximum_load = max(maximum_load, load)
        if water_on:
            water_remaining_kws -= 1.5
            if water_remaining_kws <= 1e-9 and water_completed_ms is None:
                water_completed_ms = now + STEP_MS
        if window_open:
            co2 = max(900.0, co2 - 5.0)
            temp -= 0.0015 * max(temp - 8.0, 0.0)
            if co2 <= 900 and close_at is None:
                close_at = now + STEP_MS + 3000
        if heat_on:
            temp = min(21.0, temp + 0.025)
            heater_energy_wh += 2.0 * 1000 / 3600
            if window_open:
                window_heat_ms += STEP_MS
        if temp >= 21.0 - 1e-9 and heat_completed_ms is None:
            heat_completed_ms = now + STEP_MS
        if (water_completed_ms is not None and heat_completed_ms is not None
                and vent_completed_ms is not None):
            break
    deadline = 360_000
    return {"initial_co2_ppm": initial_co2, "managed_capacity_kw": capacity_kw,
            "policy": policy, "agents": ["VentilationAgent", "ClimateAgent", "WaterAgent"],
            "vent_completion_ms": vent_completed_ms,
            "heat_completion_ms": heat_completed_ms,
            "water_completion_ms": water_completed_ms,
            "all_by_deadline": all(t is not None and t <= deadline
                                   for t in (vent_completed_ms, heat_completed_ms,
                                             water_completed_ms)),
            "peak_power_kw": maximum_load,
            "heater_energy_wh": round(heater_energy_wh, 3),
            "window_heater_overlap_ms": window_heat_ms,
            "final_co2_ppm": round(co2, 1), "final_temp_c": round(temp, 3),
            "events": trace}


def run() -> dict:
    rows = [simulate(co2, capacity, policy) for co2 in (850, 1600)
            for capacity in (3.0, 4.0) for policy in POLICIES]
    payload = {"status": "joint_uncalibrated_synthetic_mechanism_not_benchmark",
               "api_calls": 0,
               "assumptions": {"step_ms": STEP_MS, "initial_temp_c": 17,
                               "outdoor_temp_c": 8, "co2_target_ppm": 900,
                               "co2_reduction_ppm_s": 5,
                               "window_exchange_per_s": 0.0015,
                               "heater_heat_rate_c_s": 0.025,
                               "heater_kw": 2.0, "water_kw": 1.5,
                               "water_work_kws": 180,
                               "deadline_ms": 360_000,
                               "source_level": "author_hypotheses_reusing_uncalibrated_C2_rates"},
               "excluded_claims": ["real CO2/temperature trajectory", "actual water draw",
                                   "measured household capacity"],
               "rows": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps({"rows": len(run()["rows"]), "output": str(OUT)}, ensure_ascii=False))
