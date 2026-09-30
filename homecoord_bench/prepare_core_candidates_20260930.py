"""Prepare review-only C1 command and structurally new C3 laundry candidates.

The source C1 episodes are copied, never overwritten. C3 is a controlled
resource-scheduling task: all powers, periods and deadlines are explicit study
factors rather than observations of a specific home.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from probe_c3_structural_generalization import TaskSpec, make_episode_from_specs
from runtime.episode_validation import validate_event_episode
from runtime.scheduling_oracle import ideal_schedule


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "revision_drafts" / "20260927"
OUTPUT = ROOT / "revision_drafts" / "20260930_core_review"
OUTPUT_V02 = ROOT / "revision_drafts" / "20260930_core_review_v02"
LAUNDRY_SPECS = (
    TaskSpec("wash_new_load", "WasherAgent", "washer", "wash", 2.0, 60, 120, 100),
    TaskSpec("dry_prior_load", "DryerAgent", "dryer", "dry", 2.5, 65, 130, 90),
    TaskSpec("heat_room", "ClimateAgent", "heat_pump", "heat", 1.5, 90, 210, 40),
)
LAUNDRY_PRESSURES = (0.8, 1.2, 1.6)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(episode: dict[str, Any], directory: Path = OUTPUT) -> Path:
    errors = validate_event_episode(episode)
    if errors:
        raise ValueError(f"{episode['episode_id']}: {'; '.join(errors)}")
    path = directory / f"{episode['episode_id']}.json"
    path.write_text(json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def c1_command_pair() -> list[dict[str, Any]]:
    rows = []
    for source_name, condition in (
        ("HC-PAIR-C1-HVAC-CONFLICT", "overlap"),
        ("HC-PAIR-C1-HVAC-SAFE", "nonoverlap"),
    ):
        episode = _load(SOURCE / f"{source_name}.json")
        episode["episode_id"] = f"HC-C1-COMMAND-{condition.upper()}"
        episode["base_episode_id"] = "HC-C1-COMMAND"
        episode["source_type"] = "controlled_command_semantics_revision"
        episode["review_status"] = "proposed_revision_not_scored"
        episode["variant"] = {"design": "C1-command-only-v0.2", "condition": condition}
        episode["draft_notes"] = [
            "Review-only direct device command task, not a thermal comfort evaluation.",
            "The 6000 ms cooling-service interval is a controlled scheduling factor, not measured HVAC cooling time.",
            "EnergyAgent observes a peak alert but not the active comfort request.",
            "No new model proposal may be reused from the previous wording without rechecking its request.",
        ]
        values = episode["initial_state"]["values"]
        values["request"]["comfort_served"] = False
        values["grid"] = {"peak_alert": True, "peak_reduced": False}
        episode["agents"][1]["observable_state"] = [
            "devices.living_hvac", "grid.peak_alert"
        ]
        episode["task_stream"][0]["goal"] = (
            "Keep the living-room HVAC in cooling service until the active comfort session finishes."
        )
        episode["task_stream"][1]["goal"] = (
            "Respond to the peak alert by turning off the HVAC when allowed."
        )
        episode["goals"] = [
            {"path": "request.comfort_served", "op": "eq", "value": True},
            {"path": "grid.peak_reduced", "op": "eq", "value": True},
        ]
        episode["action_grounding"][0]["completion_effects"] = {
            "devices.living_hvac": "cool_24",
            "request.comfort_active": False,
            "request.comfort_served": True,
        }
        episode["action_grounding"][1]["completion_effects"] = {
            "devices.living_hvac": "forced_off", "grid.peak_reduced": True,
        }
        rows.append(episode)
    return rows


def c3_laundry_pressure_arms() -> list[dict[str, Any]]:
    rows = []
    text = {
        "wash_new_load": "Wash a new laundry load within 120 minutes.",
        "dry_prior_load": "Dry a previously washed, already-ready load within 130 minutes.",
        "heat_room": "Complete a room-heating service cycle within 210 minutes.",
    }
    for pressure in LAUNDRY_PRESSURES:
        episode = make_episode_from_specs("LAUNDRY_HEAT", LAUNDRY_SPECS, pressure)
        episode["source_type"] = "controlled_new_structural_candidate"
        episode["review_status"] = "proposed_revision_not_scored"
        episode["variant"] = {
            "design": "C3-laundry-heat-v0.1", "condition": f"rho={pressure:g}"
        }
        episode["scenario_assumptions"].update({
            "load_relationship": (
                "The dryer holds a prior washed load; the washer handles a different new load. "
                "There is no wash-to-dry dependency in this episode."
            ),
            "remote_control": "assumed virtual appliance capability, not device-verified",
            "purpose": "structurally different controlled C3 validation candidate",
        })
        for task in episode["task_stream"]:
            task["goal"] = text[task["task_id"]]
        rows.append(episode)
    return rows


def run() -> list[Path]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    episodes = c1_command_pair() + c3_laundry_pressure_arms()
    return [_save(episode) for episode in episodes]


def run_v02() -> list[Path]:
    """Preserve v0.1 and repair only its provably infeasible ρ=1.6 arm."""
    OUTPUT_V02.mkdir(parents=True, exist_ok=True)
    specs = tuple(replace(task, deadline_min=240) if task.task_id == "heat_room"
                  else task for task in LAUNDRY_SPECS)
    paths = []
    for pressure in LAUNDRY_PRESSURES:
        episode = make_episode_from_specs("LAUNDRY_HEAT_V02", specs, pressure)
        episode["source_type"] = "controlled_feasibility_repair_candidate"
        episode["review_status"] = "proposed_revision_not_scored"
        episode["variant"] = {
            "design": "C3-laundry-heat-v0.2", "condition": f"rho={pressure:g}"
        }
        episode["scenario_assumptions"].update({
            "load_relationship": (
                "The dryer holds a prior washed load; the washer handles a different new load. "
                "There is no wash-to-dry dependency in this episode."
            ),
            "remote_control": "assumed virtual appliance capability, not device-verified",
            "revision_reason": (
                "v0.1 ρ=1.6 had no all-deadline-feasible schedule even for a full-information oracle; "
                "only the flexible heating deadline changes from 210 to 240 minutes."
            ),
        })
        for task in episode["task_stream"]:
            task["goal"] = {
                "wash_new_load": "Wash a new laundry load within 120 minutes.",
                "dry_prior_load": "Dry a previously washed, already-ready load within 130 minutes.",
                "heat_room": "Complete a room-heating service cycle within 240 minutes.",
            }[task["task_id"]]
        if ideal_schedule(episode) is None:
            raise ValueError(f"v0.2 remains infeasible at ρ={pressure:g}")
        paths.append(_save(episode, OUTPUT_V02))
    return paths


if __name__ == "__main__":
    print(json.dumps([str(path) for path in run()], ensure_ascii=False, indent=2))
