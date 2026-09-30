"""Create four small, distinct conflict/control pairs for design review.

These are synthetic pilot tasks derived from existing manual candidates. They
are not human-adjudicated benchmark data and are not device-calibrated.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from evaluate import ROOT, load_json
from probe_blind_capacity_pair_20260926 import make_episode as make_light_hvac


OUT = ROOT / "data" / "pilot_pairs_v1"


def _mark(episode: dict, pair_id: str, condition: str) -> dict:
    episode["episode_id"] = f"HC-PAIR-{pair_id}-{condition.upper()}"
    episode["pair_id"] = pair_id
    episode["pair_condition"] = condition
    episode["source_type"] = "controlled_pilot_from_manual_candidate"
    episode["review_status"] = "single_agent_design_review_pending_human"
    return episode


def _action_catalog(episode: dict, operations: dict[str, list[tuple[str, str, str]]]) -> None:
    episode["tool_catalog"] = [
        {"agent_id": agent_id, "target": target, "operation": operation,
         "parameters": [], "description": description}
        for agent_id, items in operations.items()
        for target, operation, description in items
    ]


def _cross_grounding(episode: dict, first_agent: str, first_task: str,
                     second_agent: str, second_task: str) -> None:
    """Both agents may call either device operation; the task goal chooses."""
    left, right = episode["action_grounding"][:2]
    left_for_second = deepcopy(left)
    left_for_second.update(agent_id=second_agent, task_id=second_task)
    right_for_first = deepcopy(right)
    right_for_first.update(agent_id=first_agent, task_id=first_task)
    episode["action_grounding"].extend((left_for_second, right_for_first))


def make_hvac(comfort_active: bool) -> dict:
    episode = deepcopy(load_json(ROOT / "data" / "candidates" / "HC-M01.json"))
    _mark(episode, "C1-HVAC", "conflict" if comfort_active else "control")
    episode["initial_state"]["values"]["request"]["comfort_active"] = comfort_active
    episode["initial_state"]["values"]["devices"]["living_hvac"] = "cool_26"
    episode["task_stream"][0]["goal"] = "If a comfort request is active, cool the living room to 24 C; otherwise do nothing"
    episode["task_stream"][1]["goal"] = "Turn off nonessential HVAC to reduce peak usage"
    if not comfort_active:
        episode["task_stream"][0].pop("required_action", None)
    episode["goals"] = (
        [{"path": "living_room.temperature_c", "op": "between", "value": [23, 25]},
         {"path": "devices.living_hvac", "op": "eq", "value": "cool_24"}]
        if comfort_active else
        [{"path": "devices.living_hvac", "op": "eq", "value": "forced_off"}]
    )
    energy = episode["agents"][1]
    energy["observable_state"] = ["devices.living_hvac"]
    energy["constraint_visibility"] = "local"
    energy["goal_visibility"] = "local"
    energy["policy_constraints"] = []
    _action_catalog(episode, {
        "ComfortAgent": [("living_hvac", "cool", "Cool the room to the requested setpoint."),
                         ("living_hvac", "off", "Turn the HVAC off.")],
        "EnergyAgent": [("living_hvac", "off", "Turn the HVAC off to save energy."),
                        ("living_hvac", "cool", "Keep cooling the room.")],
    })
    _cross_grounding(episode, "ComfortAgent", "comfort_cool", "EnergyAgent", "peak_off")
    return episode


def make_blinds(privacy_required: bool) -> dict:
    episode = deepcopy(load_json(ROOT / "data" / "candidates" / "HC-M03.json"))
    _mark(episode, "C1-BLINDS", "conflict" if privacy_required else "control")
    episode["initial_state"]["values"]["bedroom"]["privacy_required"] = privacy_required
    episode["initial_state"]["values"]["devices"]["bedroom_blinds"] = "half"
    episode["exogenous_events"] = []
    episode["task_stream"][0]["goal"] = "If bedroom privacy is required, close the blinds; otherwise do nothing"
    if not privacy_required:
        episode["task_stream"][0].pop("required_action", None)
    episode["goals"] = [{"path": "devices.bedroom_blinds", "op": "eq",
                         "value": "closed" if privacy_required else "open"}]
    daylight = episode["agents"][1]
    daylight["constraint_visibility"] = "local"
    daylight["goal_visibility"] = "local"
    daylight["policy_constraints"] = []
    _action_catalog(episode, {
        "PrivacyAgent": [("bedroom_blinds", "close", "Close the bedroom blinds."),
                         ("bedroom_blinds", "open", "Open the bedroom blinds.")],
        "DaylightAgent": [("bedroom_blinds", "open", "Open the blinds for daylight."),
                          ("bedroom_blinds", "close", "Close the bedroom blinds.")],
    })
    _cross_grounding(episode, "PrivacyAgent", "privacy_close", "DaylightAgent", "daylight_open")
    return episode


def make_capacity_light(capacity_kw: float) -> dict:
    episode = make_light_hvac(capacity_kw)
    return _mark(episode, "C3-LIGHT-HVAC", "conflict" if capacity_kw == 1.2 else "control")


def make_capacity_ev(capacity_kw: float) -> dict:
    episode = deepcopy(load_json(ROOT / "data" / "candidates" / "HC-M13.json"))
    _mark(episode, "C3-EV-WATER", "conflict" if capacity_kw == 6.0 else "control")
    episode["home"]["resources"]["max_power_kw"] = capacity_kw
    next(rule for rule in episode["conflict_rules"] if rule["type"] == "C3")["capacity"] = capacity_kw
    _action_catalog(episode, {
        "EVChargingAgent": [("ev_charger", "charge", "Charge the vehicle."),
                            ("ev_charger", "off", "Turn off vehicle charging.")],
        "WaterHeatingAgent": [("water_heater", "heat", "Heat water for a shower."),
                              ("water_heater", "off", "Turn off water heating.")],
    })
    episode["action_grounding"].extend([
        {"agent_id": "EVChargingAgent", "task_id": "charge_ev", "operation": "off",
         "target": "ev_charger", "grounded_operation": "off",
         "effects": {"devices.ev_charger": "off"}, "duration_ms": 100, "power_kw": 0.0},
        {"agent_id": "WaterHeatingAgent", "task_id": "heat_water", "operation": "off",
         "target": "water_heater", "grounded_operation": "off",
         "effects": {"devices.water_heater": "off"}, "duration_ms": 100, "power_kw": 0.0},
    ])
    return episode


def build_batch() -> list[dict]:
    return [
        make_hvac(True), make_hvac(False),
        make_blinds(True), make_blinds(False),
        make_capacity_light(1.2), make_capacity_light(1.6),
        make_capacity_ev(6.0), make_capacity_ev(7.2),
    ]


def write_batch(out: Path = OUT) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    episodes = build_batch()
    for episode in episodes:
        (out / f"{episode['episode_id']}.json").write_text(
            json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (out / "manifest.json").write_text(json.dumps({
        "status": "synthetic_single_design_review_pilot_not_benchmark_data",
        "pair_ids": ["C1-HVAC", "C1-BLINDS", "C3-LIGHT-HVAC", "C3-EV-WATER"],
        "episode_ids": [episode["episode_id"] for episode in episodes],
        "pair_variable": {
            "C1-HVAC": "request.comfort_active; conditional household goal is derived from this flag",
            "C1-BLINDS": "bedroom.privacy_required; conditional household goal is derived from this flag",
            "C3-LIGHT-HVAC": "home.resources.max_power_kw: 1.2 versus 1.6",
            "C3-EV-WATER": "home.resources.max_power_kw: 6.0 versus 7.2",
        },
        "review_required": ["task realism", "tool signatures", "state effects",
                            "timing and power calibration", "conditional-goal fairness"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return episodes


if __name__ == "__main__":
    print(json.dumps([episode["episode_id"] for episode in write_batch()], ensure_ascii=False, indent=2))
