"""Blind, paired C3 pilot with real model proposals and a synthetic device clock.

Each specialist receives two callable actions but no required_action or
action_template. The same proposals and measured logical API latencies are
replayed at low and high household power capacity.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns

from evaluate import ROOT, load_json
from run_coordination_value_pilot import difference, metrics
from run_protocol_pilot import INSTRUCTIONS
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.execution import run_closed_loop_episode
from runtime.replay_client import MemoryReplayClient


RUN_DIR = ROOT / "runs" / "blind_capacity_pair_20260926"
OUTPUT = ROOT / "results" / "blind_capacity_pair_20260926.json"
PILOT_INSTRUCTIONS = INSTRUCTIONS + (
    " The available_actions catalog gives the exact target, operation, and parameter names "
    "for callable device actions. Choose from that catalog; an action is a proposal, not execution."
)


def make_episode(capacity_kw: float) -> dict:
    episode = deepcopy(load_json(ROOT / "data" / "candidates" / "HC-M11.json"))
    episode["episode_id"] = f"HC-BLIND-C3-cap-{str(capacity_kw).replace('.', 'p')}"
    episode["base_episode_id"] = "HC-M11"
    episode["source_type"] = "controlled_pilot_from_candidate"
    episode["review_status"] = "unreviewed_pilot"
    episode["home"]["resources"]["max_power_kw"] = capacity_kw
    next(rule for rule in episode["conflict_rules"] if rule["type"] == "C3")["capacity"] = capacity_kw
    episode["tool_catalog"] = [
        {"agent_id": "StudyLightAgent", "target": "study_light", "operation": "set_reading",
         "parameters": [{"name": "lux", "type": "number", "example": 500}],
         "description": "Turn on the study light in reading mode."},
        {"agent_id": "StudyLightAgent", "target": "study_light", "operation": "off",
         "parameters": [], "description": "Turn off the study light."},
        {"agent_id": "BedroomClimateAgent", "target": "bedroom_hvac", "operation": "cool",
         "parameters": [{"name": "temperature_c", "type": "number", "example": 25}],
         "description": "Cool the bedroom to the chosen temperature."},
        {"agent_id": "BedroomClimateAgent", "target": "bedroom_hvac", "operation": "off",
         "parameters": [], "description": "Turn off the bedroom HVAC."},
    ]
    episode["action_grounding"].extend([
        {"agent_id": "StudyLightAgent", "task_id": "study_light", "operation": "off",
         "target": "study_light", "grounded_operation": "off",
         "effects": {"devices.study_light": "off", "study.lux": 100},
         "duration_ms": 100, "power_kw": 0.0},
        {"agent_id": "BedroomClimateAgent", "task_id": "bedroom_cool", "operation": "off",
         "target": "bedroom_hvac", "grounded_operation": "off",
         "effects": {"devices.bedroom_hvac": "off"},
         "duration_ms": 100, "power_kw": 0.0},
    ])
    return episode


class RecordingClient:
    def __init__(self, underlying: DeepSeekResponsesClient):
        self.underlying = underlying
        self.records = []
        self.last_latency_ms = 0

    def decide(self, request: dict, instructions: str = "") -> dict:
        started = perf_counter_ns()
        decision = self.underlying.decide(request, instructions)
        self.last_latency_ms = max(1, round((perf_counter_ns() - started) / 1_000_000))
        self.records.append({"request": deepcopy(request), "decision": deepcopy(decision),
                             "logical_latency_ms": self.last_latency_ms})
        return decision


def run(repetitions: int) -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    low, high = make_episode(1.2), make_episode(1.6)
    (RUN_DIR / "low_capacity_episode.json").write_text(json.dumps(low, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "high_capacity_episode.json").write_text(json.dumps(high, ensure_ascii=False, indent=2), encoding="utf-8")
    logger = EventLogger(RUN_DIR / "model_events.jsonl", "blind-capacity-pair-20260926")
    model = DeepSeekResponsesClient(model="deepseek-flash", logger=logger)
    rows = []
    for repetition in range(1, repetitions + 1):
        recorder = RecordingClient(model)
        try:
            # The source run gathers exactly two blind model decisions.
            source_trace, source_result = run_closed_loop_episode(
                low, recorder, "IndependentMultiAgent", PILOT_INSTRUCTIONS, synthetic_latency=False
            )
            outcomes = {}
            for label, episode in (("low", low), ("high", high)):
                for architecture in ("IndependentMultiAgent", "ConstraintCoordinator"):
                    if label == "low" and architecture == "IndependentMultiAgent":
                        trace, result = source_trace, source_result
                    else:
                        replay = MemoryReplayClient(recorder.records)
                        trace, result = run_closed_loop_episode(
                            episode, replay, architecture, PILOT_INSTRUCTIONS, synthetic_latency=False
                        )
                        replay.assert_consumed()
                    outcomes[f"{label}_{architecture}"] = metrics(
                        trace, result, episode["episode_release_at_ms"]
                    )
            low_i = outcomes["low_IndependentMultiAgent"]
            low_c = outcomes["low_ConstraintCoordinator"]
            high_i = outcomes["high_IndependentMultiAgent"]
            high_c = outcomes["high_ConstraintCoordinator"]
            row = {
                "repetition": repetition, "model_records": recorder.records,
                "outcomes": outcomes,
                "low_goal_delay_ms": difference(low_c, low_i, "goal_first_satisfied_ms"),
                "high_goal_delay_ms": difference(high_c, high_i, "goal_first_satisfied_ms"),
            }
        except Exception as exc:
            row = {"repetition": repetition, "model_records": recorder.records,
                   "error_type": type(exc).__name__, "error": str(exc)[:500]}
        rows.append(row)
        OUTPUT.write_text(json.dumps({"experiment": "blind_capacity_pair", "rows": rows},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"repetition": repetition,
                          "action_counts": [len(x["decision"].get("actions", [])) for x in recorder.records],
                          "low_goal_delay_ms": row.get("low_goal_delay_ms"),
                          "high_goal_delay_ms": row.get("high_goal_delay_ms"),
                          "error_type": row.get("error_type")}, ensure_ascii=False), flush=True)
    return {"experiment": "blind_capacity_pair", "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=8)
    args = parser.parse_args()
    run(args.repetitions)
