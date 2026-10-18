"""M03 controlled mechanism pilot: three agents, direct HVAC and power coupling.

This synthetic test does not establish household frequency, physical timing,
or a gap beyond strong deterministic rules. It uses a 2x2 paired design.
"""

from __future__ import annotations

import json
from copy import deepcopy

from evaluate import ROOT
from generate_provenance_pilot import make_c1, make_c3
from runtime.dry_run import DryRunClient
from runtime.episode_validation import validate_event_episode
from runtime.event_simulator import run_event_simulation

OUTPUT = ROOT / "results" / "m03_c1_c3_coupled_mechanism_20260928.json"
POLICIES = (
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
    "CapacityAwareDeadlineCoordinator",
    "CentralSingleAgent",
)
CAPACITY = {"tight": 4.0, "loose": 5.4}
ENERGY_RELEASE_MS = {"overlap": 200, "nonoverlap": 6500}


def make_episode(overlap: str, capacity: str) -> dict:
    if overlap not in ENERGY_RELEASE_MS or capacity not in CAPACITY:
        raise ValueError((overlap, capacity))
    c1 = next(item for item in make_c1() if item["episode_id"].endswith(overlap.upper()))
    c3 = make_c3()[0]
    episode = deepcopy(c1)
    ev_agent = next(item for item in c3["agents"] if item["agent_id"] == "EVChargingAgent")
    ev_task = next(item for item in c3["task_stream"] if item["task_id"] == "charge_ev")
    episode["agents"].append(deepcopy(ev_agent))
    episode["task_stream"].append(deepcopy(ev_task))
    episode["action_grounding"].extend(
        deepcopy(item) for item in c3["action_grounding"]
        if item["agent_id"] == "EVChargingAgent"
    )
    ev_agent_copy = episode["agents"][-1]
    ev_agent_copy["tools"] = ["charge_ev", "stop_ev"]
    for item in c3["tool_catalog"]:
        if item["agent_id"] != "EVChargingAgent":
            continue
        tool = deepcopy(item)
        tool["tool_name"] = "charge_ev" if tool["operation"] == "charge" else "stop_ev"
        episode["tool_catalog"].append(tool)
    episode["initial_state"]["values"]["vehicle"] = deepcopy(
        c3["initial_state"]["values"]["vehicle"]
    )
    episode["initial_state"]["values"]["devices"]["ev_charger"] = "off"
    episode["goals"].append({"path": "vehicle.battery_pct", "op": "gte", "value": 50})
    comfort = next(item for item in episode["task_stream"] if item["task_id"] == "comfort_cool")
    comfort["completion_deadline_ms"] = 6200  # synthetic command-cycle deadline
    comfort["action_template"]["requires"] = [
        {"path": "request.comfort_active", "op": "eq", "value": True}
    ]
    comfort_tool = next(item for item in episode["tool_catalog"]
                        if item["agent_id"] == "ComfortAgent")
    comfort_tool["preconditions"] = deepcopy(comfort["action_template"]["requires"])
    energy = next(item for item in episode["task_stream"] if item["task_id"] == "peak_off")
    energy["release_at_ms"] = ENERGY_RELEASE_MS[overlap]
    energy["completion_deadline_ms"] = 10000
    ev_task_copy = next(item for item in episode["task_stream"] if item["task_id"] == "charge_ev")
    ev_task_copy["completion_deadline_ms"] = 6 * 60 * 60 * 1000
    kw = CAPACITY[capacity]
    episode["home"]["resources"] = {
        "max_power_kw": kw,
        "capacity_scope": "synthetic_managed_load_budget",
        "task_power_bounds_kw": {"comfort_cool": 1.4, "peak_off": 0.0, "charge_ev": 4.0},
    }
    episode["conflict_rules"].append({"type": "C3", "capacity": kw})
    episode["episode_id"] = f"HC-M03-{overlap.upper()}-{capacity.upper()}"
    episode["base_episode_id"] = "HC-M03"
    episode["source_type"] = "controlled_combination_of_unreviewed_c1_c3_mechanism_pilots"
    episode["review_status"] = "author_mechanism_pilot_not_benchmark"
    episode["data_tier"] = "mechanism_only"
    episode["variant"] = {
        "overlap": overlap, "capacity": capacity,
        "factors": ["energy_task_release_at_ms", "managed_load_budget_kw"],
    }
    episode["calibration"] = {
        "status": "synthetic_command_and_power_timing",
        "physical_parameters_verified": False,
        "excluded_claims": ["real_household_power", "real_temperature", "real_latency"],
    }
    episode["parameter_provenance"]["managed_load_budget_kw"] = {
        "value": kw, "class": "controlled_experimental_factor"
    }
    episode["parameter_provenance"]["energy_task_release_at_ms"] = {
        "value": ENERGY_RELEASE_MS[overlap], "class": "controlled_experimental_factor"
    }
    issues = validate_event_episode(episode)
    if issues:
        raise ValueError((episode["episode_id"], issues))
    return episode


def run() -> dict:
    rows = []
    for overlap in ENERGY_RELEASE_MS:
        for capacity in CAPACITY:
            episode = make_episode(overlap, capacity)
            for policy in POLICIES:
                trace, result = run_event_simulation(
                    deepcopy(episode), DryRunClient(), policy, "",
                    shared_safety_gate=True,
                )
                rows.append({
                    "condition": {"overlap": overlap, "capacity": capacity},
                    "episode_id": episode["episode_id"],
                    "policy": policy,
                    "process_valid_success": result["process_valid_success"],
                    "task_service": result["task_service"],
                    "final_goal_success": result["final_goal_success"],
                    "task_deadline_met": result["task_deadline_met"],
                    "all_deadlines_met": result["all_deadlines_met"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "shared_safety_gate_rejection_count": result["shared_safety_gate_rejection_count"],
                    "action_rejections": [
                        event.get("reason") for event in trace["events"]
                        if event["type"] == "action_rejected"
                    ],
                    "action_start_order": [
                        event["task_id"] for event in trace["events"]
                        if event["type"] == "action_started"
                    ],
                })
    report = {
        "status": "synthetic_unreviewed_coupled_mechanism_probe",
        "api_calls": 0,
        "factors": {
            "energy_task_release_at_ms": ENERGY_RELEASE_MS,
            "managed_load_budget_kw": CAPACITY,
        },
        "source_limitations": [
            "HVAC comfort is a command/service window, not measured temperature.",
            "EV power and managed capacity are synthetic assumptions.",
            "DryRun proposal latency does not measure concurrent model or device time.",
        ],
        "episodes": [
            make_episode(overlap, capacity)
            for overlap in ENERGY_RELEASE_MS for capacity in CAPACITY
        ],
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "episodes": len(result["episodes"]),
        "policy_runs": len(result["rows"]),
        "output": str(OUTPUT),
    }, ensure_ascii=False))


