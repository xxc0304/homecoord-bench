"""Dimensionally consistent EV/water scheduling pilot with completion events.

The device parameters are explicit assumptions, not calibrated observations.
Model proposals are sampled once per specialist and reused for the paired
capacity conditions. Device goals change only when the assumed work completes.
"""

from __future__ import annotations

import argparse
import json
import math
from time import perf_counter_ns

from evaluate import ROOT
from make_paired_task_batch_v1 import make_capacity_ev
from probe_blind_capacity_pair_20260926 import PILOT_INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.protocol import build_agent_request


DATA_DIR = ROOT / "data" / "pilot_physical_v2"
RUN_DIR = ROOT / "runs" / "physical_capacity_v2"
OUTPUT = ROOT / "results" / "physical_capacity_v2.json"
CAPACITY_KW = {"conflict": 6.0, "control": 7.2}
BATTERY_KWH = 60.0
CHARGE_POWER_KW = 4.0
HEATER_POWER_KW = 3.0
EFFICIENCY = 0.9
WATER_LITERS = 100.0
WATER_HEAT_KJ_PER_KG_C = 4.186
TARGET_BATTERY_PCT = 50
TARGET_WATER_C = 50
EV_DEADLINE_MS = 19_200_000  # 5 h 20 min; constructed near an ordering boundary
WATER_DEADLINE_MS = 21_600_000  # 6 h
DEADLINE_SENSITIVITY_MS = (18_000_000, 18_600_000, 19_200_000, 19_800_000, 20_700_000, 21_600_000)
POLICIES = ("ImmediateFIFO", "WaitReleasedPriority", "WaitReleasedPriorityCapacityAware")


def physical_work_ms() -> dict[str, int]:
    ev_kwh = BATTERY_KWH * (TARGET_BATTERY_PCT - 20) / 100
    water_kwh = WATER_LITERS * WATER_HEAT_KJ_PER_KG_C * (TARGET_WATER_C - 35) / 3600
    return {
        "charge_ev": math.ceil(ev_kwh / (CHARGE_POWER_KW * EFFICIENCY) * 3_600_000),
        "heat_water": math.ceil(water_kwh / (HEATER_POWER_KW * EFFICIENCY) * 3_600_000),
    }


def make_episode(condition: str) -> dict:
    episode = make_capacity_ev(CAPACITY_KW[condition])
    episode["episode_id"] = f"HC-PHYSICAL-V2-EV-WATER-{condition.upper()}"
    episode["base_episode_id"] = "HC-M13"
    episode["source_type"] = "dimensionally_consistent_assumption_pilot"
    episode["review_status"] = "unreviewed_assumptions_not_device_calibrated"
    state = episode["initial_state"]["values"]
    state["vehicle"]["battery_capacity_kwh"] = BATTERY_KWH
    state["vehicle"]["departure_deadline_ms"] = EV_DEADLINE_MS
    state["water"]["tank_liters"] = WATER_LITERS
    state["water"]["shower_deadline_ms"] = WATER_DEADLINE_MS
    episode["agents"][0]["observable_state"].extend(["vehicle.battery_capacity_kwh"])
    episode["agents"][1]["observable_state"].extend(["water.tank_liters", "water.shower_deadline_ms"])
    episode["task_stream"][0]["completion_deadline_ms"] = EV_DEADLINE_MS
    episode["task_stream"][1]["completion_deadline_ms"] = WATER_DEADLINE_MS
    episode["task_stream"][0]["goal"] = "Charge the 60 kWh EV battery from 20% to at least 50% before departure in 5 h 20 min."
    episode["task_stream"][1]["goal"] = "Heat the 100 L water tank from 35 C to at least 50 C before a shower in 6 h."
    episode["physical_assumptions"] = {
        "battery_capacity_kwh": BATTERY_KWH,
        "charger_input_kw": CHARGE_POWER_KW,
        "water_heater_input_kw": HEATER_POWER_KW,
        "efficiency": EFFICIENCY,
        "tank_liters": WATER_LITERS,
        "water_density_kg_per_liter": 1.0,
        "water_specific_heat_kj_per_kg_c": WATER_HEAT_KJ_PER_KG_C,
        "status": "assumed_not_measured",
        "effect_phase": "physical_completion",
    }
    durations = physical_work_ms()
    for grounding in episode["action_grounding"]:
        if grounding["operation"] == "charge":
            grounding["duration_ms"] = durations["charge_ev"]
            grounding["start_effects"] = {"devices.ev_charger": "charging"}
            grounding["completion_effects"] = {
                "devices.ev_charger": "complete",
                "vehicle.battery_pct": TARGET_BATTERY_PCT,
            }
        elif grounding["operation"] == "heat":
            grounding["duration_ms"] = durations["heat_water"]
            grounding["start_effects"] = {"devices.water_heater": "heating"}
            grounding["completion_effects"] = {
                "devices.water_heater": "idle",
                "water.temperature_c": TARGET_WATER_C,
            }
    for task in episode["task_stream"]:
        task["action_template"]["duration_ms"] = durations[task["task_id"]]
    for action in episode["tool_catalog"]:
        if action["operation"] == "charge":
            action["parameters"] = [{"name": "target_battery_pct", "type": "number"}]
            action["description"] = "Charge the EV to the requested battery percentage."
        elif action["operation"] == "heat":
            action["parameters"] = [{"name": "target_temperature_c", "type": "number"}]
            action["description"] = "Heat the tank to the requested temperature."
    return episode


def _sample(client: DeepSeekResponsesClient, episode: dict, task_index: int) -> dict:
    task = episode["task_stream"][task_index]
    agent = episode["agents"][task_index]
    request = build_agent_request(
        episode, agent, task, architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
    )
    assert "required_action" not in request["task"] and "action_template" not in request["task"]
    started = perf_counter_ns()
    decision = client.decide(request, PILOT_INSTRUCTIONS)
    return {"request": request, "decision": decision,
            "logical_latency_ms": max(1, round((perf_counter_ns() - started) / 1_000_000))}


def _chosen_work(record: dict, task_id: str, release_ms: int) -> dict | None:
    actions = record["decision"].get("actions", [])
    if len(actions) != 1:
        return None
    action = actions[0]
    expected = {"charge_ev": ("ev_charger", "charge"),
                "heat_water": ("water_heater", "heat")}[task_id]
    if (action.get("target"), action.get("operation")) != expected:
        return None
    parameters = {item.get("name"): item.get("value")
                  for item in action.get("parameters", []) if isinstance(item, dict)}
    required_name, target_value = {
        "charge_ev": ("target_battery_pct", TARGET_BATTERY_PCT),
        "heat_water": ("target_temperature_c", TARGET_WATER_C),
    }[task_id]
    proposed = parameters.get(required_name)
    if isinstance(proposed, bool) or not isinstance(proposed, (int, float)) or proposed != target_value:
        return None
    return {
        "task_id": task_id,
        "ready_ms": release_ms + record["logical_latency_ms"],
        "duration_ms": physical_work_ms()[task_id],
        "power_kw": {"charge_ev": CHARGE_POWER_KW,
                     "heat_water": HEATER_POWER_KW}[task_id],
    }


def schedule(episode: dict, records: dict[str, dict], policy: str) -> dict:
    if policy not in POLICIES:
        raise ValueError(policy)
    tasks = {item["task_id"]: item for item in episode["task_stream"]}
    works = [work for task_id, record in records.items()
             if (work := _chosen_work(record, task_id, tasks[task_id]["release_at_ms"])) is not None]
    works.sort(key=lambda item: (item["ready_ms"], item["task_id"]))
    capacity = episode["home"]["resources"]["max_power_kw"]
    wait_for_urgent = (
        len(works) == 2
        and works[0]["task_id"] == "heat_water"
        and tasks["charge_ev"]["release_at_ms"] <= works[0]["ready_ms"]
        and policy != "ImmediateFIFO"
        and (policy != "WaitReleasedPriorityCapacityAware"
             or CHARGE_POWER_KW + HEATER_POWER_KW > capacity)
    )
    if wait_for_urgent:
        works.sort(key=lambda item: 0 if item["task_id"] == "charge_ev" else 1)
    events = []
    for work in works:
        start = work["ready_ms"]
        if wait_for_urgent and work["task_id"] == "heat_water":
            # Waiting reveals the urgent proposal; it does not by itself
            # require holding this action until the urgent device finishes.
            start = max(start, events[0]["start_ms"])
        if events and sum(event["power_kw"] for event in events
                          if event["start_ms"] <= start < event["finish_ms"]) + work["power_kw"] > capacity:
            start = max(start, max(event["finish_ms"] for event in events))
        events.append({
            "task_id": work["task_id"], "ready_ms": work["ready_ms"],
            "start_ms": start, "finish_ms": start + work["duration_ms"],
            "power_kw": work["power_kw"],
        })
    completed = {event["task_id"]: event["finish_ms"] for event in events}
    safe = all(
        not (a["start_ms"] < b["finish_ms"] and b["start_ms"] < a["finish_ms"])
        or a["power_kw"] + b["power_kw"] <= capacity
        for index, a in enumerate(events) for b in events[index + 1:]
    )
    return {
        "policy": policy, "condition": episode["pair_condition"],
        "events": events, "safe": safe,
        "first_physical_start_ms": min((x["start_ms"] for x in events), default=None),
        "physical_completion_ms": completed,
        "all_tasks_completed": set(completed) == {"charge_ev", "heat_water"},
        "ev_deadline_met": completed.get("charge_ev", math.inf) <= EV_DEADLINE_MS,
        "water_deadline_met": completed.get("heat_water", math.inf) <= WATER_DEADLINE_MS,
        "ev_deadline_sensitivity": {
            str(deadline): completed.get("charge_ev", math.inf) <= deadline
            for deadline in DEADLINE_SENSITIVITY_MS
        },
        "waited_for_urgent": wait_for_urgent,
    }


def run(repetitions: int) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    episodes = {condition: make_episode(condition) for condition in CAPACITY_KW}
    for condition, episode in episodes.items():
        (DATA_DIR / f"{condition}.json").write_text(
            json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    rows = []
    if OUTPUT.exists():
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if previous.get("assumptions") != episodes["conflict"]["physical_assumptions"]:
            raise ValueError("existing result uses different physical assumptions")
        rows = previous["rows"]
        for row in rows:
            if "model_records" in row:
                row["outcomes"] = {
                    condition: {policy: schedule(episode, row["model_records"], policy)
                                for policy in POLICIES}
                    for condition, episode in episodes.items()
                }
        OUTPUT.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "physical-capacity-v2")
    client = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    done = {row["repetition"] for row in rows if "outcomes" in row}
    for repetition in range(1, repetitions + 1):
        if repetition in done:
            continue
        row = {"repetition": repetition}
        try:
            records = {
                "charge_ev": _sample(client, episodes["conflict"], 0),
                "heat_water": _sample(client, episodes["conflict"], 1),
            }
            row["model_records"] = records
            row["outcomes"] = {
                condition: {policy: schedule(episode, records, policy)
                            for policy in POLICIES}
                for condition, episode in episodes.items()
            }
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)[:500]
        rows.append(row)
        OUTPUT.write_text(json.dumps({
            "status": "dimensionally_consistent_assumptions_not_device_calibration",
            "model": "deepseek-flash",
            "assumptions": episodes["conflict"]["physical_assumptions"],
            "rows": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"repetition": repetition, "error": row.get("error_type"),
                          "decisions": {key: rec["decision"]["response_type"]
                                        for key, rec in row.get("model_records", {}).items()}},
                         ensure_ascii=False), flush=True)
    return {"rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    run(parser.parse_args().repetitions)
