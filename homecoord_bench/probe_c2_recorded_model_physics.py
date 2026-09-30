"""Pair real specialist proposals with the isolated synthetic C2 room model.

Only the initial open/heat/noop decisions come from DeepSeek. A deterministic
window controller closes at the CO2 target, and a thermostat heats to target.
The room dynamics are uncalibrated; this is an exploratory integration test.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from time import perf_counter_ns

from evaluate import ROOT
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from probe_ventilation_heating_tradeoff import simulate
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.protocol import build_agent_request


OUTPUT = ROOT / "results" / "c2_recorded_model_physics_20260928.json"
RUN_DIR = ROOT / "runs" / "c2-recorded-model-physics-20260928"
REPETITIONS = 5
DEADLINE_MS = 360_000
VENTILATION_RATES = (2.5, 5.0)
EXCHANGE_PER_S = 0.0015
POLICIES = ("Independent", "DeviceLock", "ActionOverlapLock", "StateGate", "OracleSwitch")


def make_request(condition: str, role: str, repetition: int) -> dict:
    if condition not in {"conflict", "control"} or role not in {"air", "heat"}:
        raise ValueError((condition, role))
    agents = [
        {"agent_id": "AirQualityAgent", "role": "air_quality", "tools": ["set_window"],
         "observable_state": ["bedroom.co2_ppm"], "writable_resources": ["devices.window"],
         "goal_visibility": "local", "constraint_visibility": "local"},
        {"agent_id": "HeatingAgent", "role": "heating", "tools": ["set_heater"],
         "observable_state": ["bedroom.temperature_c"], "writable_resources": ["devices.heater"],
         "goal_visibility": "local", "constraint_visibility": "local"},
    ]
    tasks = [
        {"task_id": "ventilate_if_needed", "agent_id": "AirQualityAgent",
         "release_at_ms": 7000,
         "goal": "If bedroom CO2 is above 900 ppm, open the window to ventilate. "
                 "A separate device controller will close it after CO2 reaches 900 ppm; "
                 "if CO2 is already at or below 900 ppm, take no action.",
         "priority": 60},
        {"task_id": "restore_comfort_temperature", "agent_id": "HeatingAgent",
         "release_at_ms": 8000,
         "goal": "Heat the bedroom from 17 C to 21 C. A thermostat will maintain the target.",
         "priority": 80},
    ]
    episode = {
        "episode_id": f"HC-C2-MODEL-{condition}-{repetition:02d}",
        "initial_state": {"version": 106, "values": {
            "bedroom": {"temperature_c": 17, "co2_ppm": 1600 if condition == "conflict" else 850},
            "devices": {"window": "closed", "heater": "off"},
        }},
        "agents": agents,
        "task_stream": tasks,
        "goals": [], "constraints": [],
        "tool_catalog": [
            {"agent_id": "AirQualityAgent", "target": "window", "operation": "open",
             "parameters": [], "description": "Open the bedroom window; controller closes at CO2 target."},
            {"agent_id": "AirQualityAgent", "target": "window", "operation": "close",
             "parameters": [], "description": "Close the bedroom window."},
            {"agent_id": "HeatingAgent", "target": "heater", "operation": "heat_high",
             "parameters": [], "description": "Enable bedroom heating to 21 C."},
            {"agent_id": "HeatingAgent", "target": "heater", "operation": "off",
             "parameters": [], "description": "Leave heating off."},
        ],
    }
    index = 0 if role == "air" else 1
    return build_agent_request(
        episode, agents[index], tasks[index], architecture="IndependentMultiAgent",
        current_time_ms=tasks[index]["release_at_ms"],
        request_id=f"{episode['episode_id']}:{role}",
    )


def classify(record: dict, role: str) -> str:
    decision = record["decision"]
    if decision["response_type"] in {"noop", "defer"} and not decision["actions"]:
        return "no_action"
    actions = decision["actions"]
    expected = ("window", "open") if role == "air" else ("heater", "heat_high")
    if decision["response_type"] == "action_proposal" and len(actions) == 1 and (
        actions[0]["target"], actions[0]["operation"]
    ) == expected and not actions[0]["parameters"]:
        return "expected_action"
    return "other_or_invalid_action"


def replay_row(row: dict) -> list[dict]:
    records = row["model_records"]
    out = []
    for condition in ("conflict", "control"):
        air = records["air_conflict" if condition == "conflict" else "air_control"]
        heat = records["heat_shared"]
        air_class = classify(air, "air")
        heat_class = classify(heat, "heat")
        for rate in VENTILATION_RATES:
            for policy in POLICIES:
                result = simulate(
                    initial_co2_ppm=1600 if condition == "conflict" else 850,
                    ventilation_rate_ppm_s=rate,
                    open_exchange_per_s=EXCHANGE_PER_S,
                    deadline_ms=DEADLINE_MS,
                    policy=policy,
                    air_proposal_ready_ms=7000 + air["logical_latency_ms"],
                    heat_proposal_ready_ms=8000 + heat["logical_latency_ms"],
                    air_action_proposed=air_class == "expected_action",
                    heat_action_proposed=heat_class == "expected_action",
                )
                out.append({
                    "repetition": row["repetition"], "condition": condition,
                    "ventilation_rate_ppm_s": rate, "policy": policy,
                    "air_decision_class": air_class, "heat_decision_class": heat_class,
                    "air_model_latency_ms": air["logical_latency_ms"],
                    "heat_model_latency_ms": heat["logical_latency_ms"],
                    **result,
                })
    return out


def run(repetitions: int = REPETITIONS) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if payload["design"] != design():
            raise ValueError("existing output has a different frozen design")
    else:
        payload = {"status": "uncalibrated_synthetic_room_real_model_initial_proposals",
                   "model": "deepseek-flash", "design": design(), "rows": [], "replays": []}
    done = {row["repetition"] for row in payload["rows"] if "model_records" in row}
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "c2-recorded-model-physics")
    client = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    for repetition in range(1, repetitions + 1):
        if repetition in done:
            continue
        row = next((existing for existing in payload["rows"]
                    if existing["repetition"] == repetition),
                   {"repetition": repetition, "model_records": {}})
        for key, condition, role in (
            ("air_conflict", "conflict", "air"),
            ("air_control", "control", "air"),
            ("heat_shared", "conflict", "heat"),
        ):
            if key in row["model_records"]:
                continue
            request = make_request(condition, role, repetition)
            started = perf_counter_ns()
            decision = client.decide(request, PILOT_INSTRUCTIONS)
            row["model_records"][key] = {
                "request": request, "decision": deepcopy(decision),
                "logical_latency_ms": max(1, round((perf_counter_ns() - started) / 1_000_000)),
            }
            # Persist each completed call so a network interruption does not
            # silently discard already purchased proposals.
            payload["rows"] = [x for x in payload["rows"] if x["repetition"] != repetition] + [row]
            OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["replays"] = [item for complete in payload["rows"]
                              if len(complete.get("model_records", {})) == 3
                              for item in replay_row(complete)]
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"repetition": repetition,
                          "decisions": {key: classify(record, "air" if key.startswith("air") else "heat")
                                        for key, record in row["model_records"].items()}},
                         ensure_ascii=False), flush=True)
    return payload


def design() -> dict:
    return {
        "conditions": {"conflict_initial_co2_ppm": 1600, "control_initial_co2_ppm": 850},
        "single_changed_factor": "initial_co2_ppm",
        "model_requests": "air in each condition, one shared heating request per repetition",
        "task_release_ms": {"air": 7000, "heat": 8000},
        "deadline_ms": DEADLINE_MS,
        "ventilation_rate_ppm_s": list(VENTILATION_RATES),
        "open_exchange_per_s": EXCHANGE_PER_S,
        "policies": list(POLICIES),
        "physical_time_step_ms": 1000,
        "action_semantics": "model chooses initial command; window controller closes at CO2 target; thermostat heats to 21 C",
        "oracle_status": "unfair_exact_model_reference",
        "calibration_status": "none",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    args = parser.parse_args()
    report = run(args.repetitions)
    print(json.dumps({"completed_repetitions": sum(
        len(row.get("model_records", {})) == 3 for row in report["rows"]
    ), "replay_rows": len(report["replays"]), "output": str(OUTPUT)}, ensure_ascii=False))
