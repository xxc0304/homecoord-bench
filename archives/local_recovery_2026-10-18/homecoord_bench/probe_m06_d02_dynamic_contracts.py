"""M06 and D02 synthetic capability/report timing probes, without model calls."""

from __future__ import annotations

import json
from copy import deepcopy

from evaluate import ROOT
from runtime.dynamic_contracts import simulate

OUT = ROOT / "results" / "m06_d02_dynamic_contracts_20260928.json"


def base_jobs() -> list[dict]:
    # Values are controlled hypotheses, not measured appliance cycles.
    return [
        {"id": "ev", "agent": "EVAgent", "release_ms": 0,
         "modes_kw": {"high": 4.0}, "work_kws": 16.0, "deadline_ms": 8000,
         "interruptible": False, "stop_ack_ms": 200, "resume_loss_kws": 0.4},
        {"id": "water", "agent": "WaterAgent", "release_ms": 1000,
         "modes_kw": {"high": 3.8}, "work_kws": 11.4, "deadline_ms": 4600,
         "interruptible": False, "stop_ack_ms": 200, "resume_loss_kws": 0.4},
        {"id": "dryer", "agent": "DryerAgent", "release_ms": 0,
         "modes_kw": {"high": 2.2}, "work_kws": 8.8, "deadline_ms": 10_000,
         "interruptible": False, "stop_ack_ms": 200, "resume_loss_kws": 0.4},
    ]


def run() -> dict:
    rows = []
    m06_events = [{"at_ms": 0, "capacity_kw": 6.0, "report_delay_ms": 0}]
    for capability in ("fixed", "low_mode", "pause_resume"):
        jobs = base_jobs()
        if capability == "low_mode":
            jobs[0]["modes_kw"]["low"] = 2.0
            jobs[2]["modes_kw"]["low"] = 1.1
        if capability == "pause_resume":
            jobs[0]["interruptible"] = True
            jobs[2]["interruptible"] = True
        result = simulate(jobs, m06_events, mode_choice=capability == "low_mode")
        rows.append({"structure": "M06", "capability": capability,
                     "contract": deepcopy(jobs), "capacity_events": deepcopy(m06_events),
                     **result})

    for change_at in (0, 1500, 9000):
        for report_delay in (0, 1000):
            for mode_choice in (False, True):
                jobs = base_jobs()
                jobs[0]["modes_kw"]["low"] = 2.0
                jobs[2]["modes_kw"]["low"] = 1.1
                jobs[0]["interruptible"] = True
                jobs[2]["interruptible"] = True
                # At t=0, the low capacity is the initial condition rather
                # than two changes with identical timestamps.
                events = ([{"at_ms": 0, "capacity_kw": 5.0,
                            "report_delay_ms": report_delay}]
                          if change_at == 0 else
                          [{"at_ms": 0, "capacity_kw": 8.0, "report_delay_ms": 0},
                           {"at_ms": change_at, "capacity_kw": 5.0,
                            "report_delay_ms": report_delay}])
                result = simulate(jobs, events, mode_choice=mode_choice)
                rows.append({"structure": "D02", "capacity_change_at_ms": change_at,
                             "report_delay_ms": report_delay,
                             "selector": "low_mode" if mode_choice else "fixed_high",
                             "contract": deepcopy(jobs), "capacity_events": deepcopy(events),
                             **result})
    payload = {
        "status": "synthetic_device_contract_stress_only_not_benchmark",
        "api_calls": 0,
        "contract_semantics": {
            "capacity_scope": "hypothetical managed-load budget",
            "physical_interlock": "instantaneous hardware load shed; stop acknowledgement after 200 ms",
            "energy_report": "agent receives actual capacity after specified delay",
            "progress": "kW seconds of abstract work; low power conserves work rate",
            "resume_loss": "0.4 kW seconds per interrupted cycle, assumed",
            "selector": "EDF; fixed high, or conservative lowest mode; optional preemption",
            "excluded_claims": ["actual EV/dryer power modes", "actual device pause safety",
                                "actual restart loss", "real household deadlines"],
        },
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps({"rows": len(run()["rows"]), "output": str(OUT)}, ensure_ascii=False))
