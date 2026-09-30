"""One-record C2 heating-rate sensitivity; no additional model calls."""

from __future__ import annotations

import hashlib
import json

from evaluate import ROOT
from probe_c2_recorded_model_physics import classify
from probe_ventilation_heating_tradeoff import simulate


SOURCE = ROOT / "results" / "c2_recorded_model_physics_20260928.json"
OUTPUT = ROOT / "results" / "c2_heat_rate_sensitivity_20260928.json"
HEAT_RATES_C_PER_S = (0.015, 0.025, 0.035)
VENT_RATES_PPM_S = (2.5, 5.0)
POLICIES = ("Independent", "StateGate", "OracleSwitch")


def run() -> dict:
    source_bytes = SOURCE.read_bytes()
    source = json.loads(source_bytes)
    row = next(item for item in source["rows"]
               if item["repetition"] == 1 and len(item["model_records"]) == 3)
    records = row["model_records"]
    heat = records["heat_shared"]
    rows = []
    for condition, co2 in (("conflict", 1600), ("control", 850)):
        air = records["air_conflict" if condition == "conflict" else "air_control"]
        for vent_rate in VENT_RATES_PPM_S:
            for heat_rate in HEAT_RATES_C_PER_S:
                for policy in POLICIES:
                    outcome = simulate(
                        initial_co2_ppm=co2,
                        ventilation_rate_ppm_s=vent_rate,
                        open_exchange_per_s=0.0015,
                        deadline_ms=360_000,
                        policy=policy,
                        air_proposal_ready_ms=7000 + air["logical_latency_ms"],
                        heat_proposal_ready_ms=8000 + heat["logical_latency_ms"],
                        air_action_proposed=classify(air, "air") == "expected_action",
                        heat_action_proposed=classify(heat, "heat") == "expected_action",
                        heat_rate_c_per_s=heat_rate,
                    )
                    rows.append({"condition": condition, "ventilation_rate_ppm_s": vent_rate,
                                 "heat_rate_c_per_s": heat_rate, "policy": policy, **outcome})
    payload = {
        "status": "uncalibrated_synthetic_sensitivity_one_replayed_model_record",
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_repetition": 1,
        "new_api_calls": 0,
        "rates_are_alternative_assumptions_not_independent_homes": True,
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({"rows": len(result["rows"]), "output": str(OUTPUT)}, ensure_ascii=False))
