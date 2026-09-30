"""Build review-only paired drafts from three representative candidate tasks.

The canonical candidates are never modified by this generator. Drafts are
stored outside data/ so the benchmark audit and scoring suites do not mistake
them for approved episodes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CANDIDATES = ROOT / "data" / "candidates"
OUTPUT = ROOT / "revision_drafts" / "20260927"


def load_candidate(episode_id: str) -> dict[str, Any]:
    return json.loads((CANDIDATES / f"{episode_id}.json").read_text(encoding="utf-8"))


def _tool(agent_id: str, tool_name: str, description: str, target: str,
          operation: str, parameters: dict[str, Any],
          preconditions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    parameter_rows = [
        {"name": name, **schema, "required": True}
        for name, schema in parameters.items()
    ]
    return {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "description": description,
        "target": target,
        "operation": operation,
        "parameters": parameter_rows,
        "preconditions": preconditions or [],
        "returns": {"status": ["accepted", "rejected"], "observed_state": "object"},
    }


def _save(episode: dict[str, Any]) -> Path:
    path = OUTPUT / f"{episode['episode_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def make_c1_pair() -> list[dict[str, Any]]:
    source = load_candidate("HC-M01")
    drafts = []
    for episode_id, release_at, label in (
        ("HC-PAIR-C1-HVAC-CONFLICT", 200, "overlapping_cool_and_off"),
        ("HC-PAIR-C1-HVAC-SAFE", 6200, "energy_action_after_cooling_window"),
    ):
        episode = deepcopy(source)
        episode["episode_id"] = episode_id
        episode["base_episode_id"] = "HC-M01"
        episode["review_status"] = "proposed_revision_not_scored"
        episode["tool_contract_version"] = "strict-v1"
        episode["variant"] = {"revision_draft": "C1-HVAC-pair-v0.1", "condition": label}
        episode["draft_notes"] = [
            "Review-only copy; canonical HC-M01 is unchanged.",
            "C3 capacity annotation removed to isolate same-device C1.",
            "Fixed-proposal coordination replay only; not a full action-selection evaluation.",
            "Duration and power remain synthetic and require source/calibration review.",
        ]
        episode["conflict_rules"] = [rule for rule in episode["conflict_rules"] if rule["type"] == "C1"]
        episode["task_stream"][1]["release_at_ms"] = release_at
        episode["task_stream"][0]["action_template"]["duration_ms"] = 6000
        episode["task_stream"][1]["action_template"]["duration_ms"] = 500
        episode["goals"] = [episode["goals"][0]]
        episode["action_grounding"] = [
            {
                "agent_id": "ComfortAgent", "task_id": "comfort_cool", "operation": "cool",
                "target": "living_hvac", "grounded_operation": "cool",
                "start_effects": {"devices.living_hvac": "cooling"},
                "completion_effects": {
                    "devices.living_hvac": "cool_24",
                    "living_room.temperature_c": 24,
                    "request.comfort_active": False,
                },
                "effects": {"devices.living_hvac": "cooling"},
                "duration_ms": 6000, "power_kw": 1.4,
            },
            {
                "agent_id": "EnergyAgent", "task_id": "peak_off", "operation": "off",
                "target": "living_hvac", "grounded_operation": "off",
                "start_effects": {"devices.living_hvac": "forced_off"},
                "completion_effects": {"devices.living_hvac": "forced_off"},
                "effects": {"devices.living_hvac": "forced_off"},
                "duration_ms": 500, "power_kw": 0.0,
            },
        ]
        episode["tool_catalog"] = [
            _tool("ComfortAgent", "set_hvac", "Start cooling to the requested set point.",
                  "living_hvac", "cool", {"temperature_c": {"type": "number", "minimum": 16, "maximum": 30}}),
            _tool("EnergyAgent", "set_hvac", "Switch the living-room HVAC off for peak reduction.",
                  "living_hvac", "off", {}),
        ]
        episode["calibration"] = {"status": "synthetic_range", "physical_parameters_verified": False}
        drafts.append(episode)
    return drafts


def make_c3_pair() -> list[dict[str, Any]]:
    source = load_candidate("HC-M11")
    drafts = []
    for capacity, condition in (
        (1.2, "over_capacity"),
        (1.5, "exact_capacity_limit"),
        (1.7, "safe_parallel_control"),
    ):
        episode = deepcopy(source)
        episode_id = f"HC-PAIR-C3-HOME-POWER-{condition.upper().replace('_', '-')}"
        episode["episode_id"] = episode_id
        episode["base_episode_id"] = "HC-M11"
        episode["review_status"] = "proposed_revision_not_scored"
        episode["tool_contract_version"] = "strict-v1"
        episode["variant"] = {
            "revision_draft": "C3-HOME-POWER-pair-v0.1",
            "condition": condition,
            "capacity_kw": capacity,
        }
        episode["draft_notes"] = [
            "Review-only copy; canonical HC-M11 is unchanged.",
            "The pair changes only the shared capacity threshold.",
            "Power, duration and home-versus-circuit scope are not verified; keep synthetic until sourced.",
        ]
        episode["home"]["resources"]["max_power_kw"] = capacity
        next(rule for rule in episode["conflict_rules"] if rule["type"] == "C3")["capacity"] = capacity
        episode["tool_catalog"] = [
            _tool("StudyLightAgent", "set_light", "Set study lighting for the reading task.",
                  "study_light", "set_reading", {"lux": {"type": "number", "minimum": 300, "maximum": 800}}),
            _tool("BedroomClimateAgent", "set_hvac", "Start bedroom cooling at a set point.",
                  "bedroom_hvac", "cool", {"temperature_c": {"type": "number", "minimum": 18, "maximum": 30}}),
        ]
        episode["calibration"] = {"status": "synthetic_range", "physical_parameters_verified": False}
        drafts.append(episode)
    return drafts


def make_c4_timing_arms() -> list[dict[str, Any]]:
    source = load_candidate("HC-M16")
    arms = [
        ("HC-PAIR-C4-CLEAN-NO-EVENT", "no_event", None, None),
        ("HC-PAIR-C4-CLEAN-PRECOMMIT", "precommit", 350, 300),
        ("HC-PAIR-C4-CLEAN-INFLIGHT", "inflight", 500, 300),
        ("HC-PAIR-C4-CLEAN-POSTCOMPLETE", "postcomplete", 4000, 300),
    ]
    drafts = []
    for episode_id, condition, enter_at_ms, proposal_latency_ms in arms:
        episode = deepcopy(source)
        episode["episode_id"] = episode_id
        episode["base_episode_id"] = "HC-M16"
        episode["review_status"] = "proposed_revision_not_scored"
        episode["tool_contract_version"] = "strict-v1"
        episode["variant"] = {
            "revision_draft": "C4-CLEAN-TIMING-v0.1",
            "condition": condition,
            "proposal_latency_factor_ms": proposal_latency_ms,
        }
        episode["draft_notes"] = [
            "Review-only copy; canonical HC-M16 is unchanged.",
            "The exogenous event never sets the cleaning goal.",
            "Cancellation, stopping delay and resumed-cleaning behavior are not implemented in this draft.",
            "Proposal latency is an experimental factor, not an episode measurement.",
        ]
        if condition == "no_event":
            episode["exogenous_events"] = []
        else:
            episode["exogenous_events"] = [
                {"at_ms": enter_at_ms, "event": "resident_enters_bedroom",
                 "new_state_version": 117, "patch": {"bedroom.occupied": True}},
                {"at_ms": enter_at_ms + 4500, "event": "resident_leaves_bedroom",
                 "new_state_version": 118, "patch": {"bedroom.occupied": False}},
            ]
        episode["conflict_rules"] = [{
            "type": "C4",
            "task_id": "bedroom_clean",
            "invalidating_conditions": [
                {"path": "bedroom.occupied", "op": "eq", "value": False}
            ],
        }]
        episode["tool_catalog"] = [
            _tool("BedroomCleaningAgent", "start_robot", "Start bedroom cleaning if the room is unoccupied.",
                  "bedroom_robot", "clean", {}, [{"path": "bedroom.occupied", "op": "eq", "value": False}]),
            _tool("BedroomCareAgent", "observe_occupancy", "Read the bedroom occupancy sensor.",
                  "occupancy_sensor", "observe", {}),
        ]
        episode["calibration"] = {"status": "synthetic_range", "physical_parameters_verified": False}
        drafts.append(episode)
    return drafts


def make_drafts() -> list[dict[str, Any]]:
    return make_c1_pair() + make_c3_pair() + make_c4_timing_arms()


def main() -> None:
    paths = [_save(episode) for episode in make_drafts()]
    print(json.dumps({"draft_count": len(paths), "paths": [str(path) for path in paths]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
