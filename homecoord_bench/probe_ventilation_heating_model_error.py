"""HC-M06 design probe: does a simple predictive switch survive model error?

All dynamics and deadlines are inherited from the uncalibrated standalone
ventilation/heating pilot. This is a crossed uncertainty experiment, not a
SimuHome or real-device calibration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT, load_json
from probe_ventilation_heating_tradeoff import simulate


CO2_STATES = (850, 1600)
RATES = (2.5, 5.0)
EXCHANGES = (0.0005, 0.0015, 0.003)
DEADLINES_MS = (240000, 360000, 480000)


def evaluate_estimate(*, initial_co2_ppm: int, true_rate: float,
                      true_exchange: float, estimated_rate: float,
                      estimated_exchange: float, deadline_ms: int) -> dict:
    true_args = dict(initial_co2_ppm=initial_co2_ppm,
                     ventilation_rate_ppm_s=true_rate,
                     open_exchange_per_s=true_exchange, deadline_ms=deadline_ms)
    estimate_args = dict(initial_co2_ppm=initial_co2_ppm,
                         ventilation_rate_ppm_s=estimated_rate,
                         open_exchange_per_s=estimated_exchange, deadline_ms=deadline_ms)
    predicted_gate = simulate(**estimate_args, policy="StateGate")
    actual_gate = simulate(**true_args, policy="StateGate")
    actual_independent = simulate(**true_args, policy="Independent")
    actual_oracle = simulate(**true_args, policy="OracleSwitch")
    selected = "StateGate" if predicted_gate["deadline_met"] else "Independent"
    actual = actual_gate if selected == "StateGate" else actual_independent
    return {
        "initial_co2_ppm": initial_co2_ppm,
        "true_rate_ppm_s": true_rate,
        "true_exchange_per_s": true_exchange,
        "estimated_rate_ppm_s": estimated_rate,
        "estimated_exchange_per_s": estimated_exchange,
        "deadline_ms": deadline_ms,
        "estimated_equals_true": (true_rate, true_exchange) == (estimated_rate, estimated_exchange),
        "selected_policy": selected,
        "predicted_gate_completion_ms": predicted_gate["goal_completion_ms"],
        "predicted_gate_on_time": predicted_gate["deadline_met"],
        "actual_gate_on_time": actual_gate["deadline_met"],
        "actual_independent_on_time": actual_independent["deadline_met"],
        "actual_oracle_on_time": actual_oracle["deadline_met"],
        "actual_selected_on_time": actual["deadline_met"],
        "avoidable_deadline_miss": actual_oracle["deadline_met"] and not actual["deadline_met"],
        "avoidable_extra_energy_wh": round(max(0.0, actual["heater_energy_wh"] - actual_oracle["heater_energy_wh"]), 4)
            if actual["deadline_met"] and actual_oracle["deadline_met"] else None,
        "actual_selected_energy_wh": actual["heater_energy_wh"],
        "actual_oracle_energy_wh": actual_oracle["heater_energy_wh"],
        "actual_selected_completion_ms": actual["goal_completion_ms"],
    }


def summarize(rows: list[dict]) -> dict:
    return {
        "cells": len(rows),
        "distinct_true_physics": len({(r["true_rate_ppm_s"], r["true_exchange_per_s"]) for r in rows}),
        "model_mismatch_cells": sum(not r["estimated_equals_true"] for r in rows),
        "predicted_gate_on_time_actual_late": sum(r["predicted_gate_on_time"] and not r["actual_gate_on_time"] for r in rows),
        "predicted_gate_late_actual_on_time": sum(not r["predicted_gate_on_time"] and r["actual_gate_on_time"] for r in rows),
        "avoidable_deadline_misses": sum(r["avoidable_deadline_miss"] for r in rows),
        "on_time_but_extra_energy_cells": sum(r["avoidable_extra_energy_wh"] is not None and r["avoidable_extra_energy_wh"] > 0 for r in rows),
        "selected_on_time": sum(r["actual_selected_on_time"] for r in rows),
        "oracle_on_time": sum(r["actual_oracle_on_time"] for r in rows),
    }


def run(output_path: Path) -> dict:
    source = load_json(ROOT / "data" / "candidates" / "HC-M06.json")
    rows = [evaluate_estimate(initial_co2_ppm=co2, true_rate=true_rate,
                              true_exchange=true_exchange,
                              estimated_rate=estimate_rate,
                              estimated_exchange=estimate_exchange,
                              deadline_ms=deadline)
            for co2 in CO2_STATES
            for true_rate in RATES for true_exchange in EXCHANGES
            for estimate_rate in RATES for estimate_exchange in EXCHANGES
            for deadline in DEADLINES_MS]
    conflict = [r for r in rows if r["initial_co2_ppm"] == 1600]
    control = [r for r in rows if r["initial_co2_ppm"] == 850]
    summary = {"conflict": summarize(conflict), "control": summarize(control),
               "conflict_exact_model": summarize([r for r in conflict if r["estimated_equals_true"]]),
               "conflict_wrong_model": summarize([r for r in conflict if not r["estimated_equals_true"]])}
    payload = {
        "experiment": "hc_m06_model_error_switch_probe",
        "status": "synthetic_uncalibrated_crossed_parameter_probe",
        "source_episode": source["episode_id"],
        "input_grid": {"initial_co2_ppm": CO2_STATES, "ventilation_rate_ppm_s": RATES,
                       "open_exchange_per_s": EXCHANGES, "deadline_ms": DEADLINES_MS},
        "decision_rule": "Estimate StateGate outcome using estimated dynamics. If forecast meets deadline, wait for window closure; otherwise start heating immediately. Actual execution uses hidden true dynamics. Compare to a perfect-model OracleSwitch with the same two choices.",
        "limitations": "True and estimated parameters are selected from the same six uncalibrated synthetic points; no SimuHome window/CO2 trace or physical-device calibration exists. The decision maker is given an estimate without paying for inference or sensing. Repeated deadlines and estimates reuse six true physical configurations, so cells are not independent samples or confidence intervals.",
        "summary": summary,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "ventilation_heating_model_error_20260927.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))
