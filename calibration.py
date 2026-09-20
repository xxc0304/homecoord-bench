"""Synthetic parameter ranges and deterministic sampling for simulator sweeps.

The ranges in this module are robustness assumptions derived from the current
nominal placeholders. They are not measurements of physical devices.
"""

from __future__ import annotations

from copy import deepcopy
import random
from typing import Any


DEFAULT_DURATION_RANGE = (0.80, 1.20)
DEFAULT_POWER_RANGE = (0.85, 1.15)


def _sample_number(rng: random.Random, nominal: float, bounds: tuple[float, float]) -> float:
    if nominal == 0:
        return 0.0
    return nominal * rng.uniform(*bounds)


def parameterize_episode(episode: dict[str, Any], replicate: int) -> dict[str, Any]:
    """Return a deterministic parameterized copy for one sensitivity replicate."""
    sampled = deepcopy(episode)
    calibration = sampled.get("calibration", {})
    duration_bounds = tuple(calibration.get("duration_relative_range", DEFAULT_DURATION_RANGE))
    power_bounds = tuple(calibration.get("power_relative_range", DEFAULT_POWER_RANGE))
    seed = f"{sampled['episode_id']}::calibration::{replicate}"
    rng = random.Random(seed)

    for grounding in sampled.get("action_grounding", []):
        nominal_duration = grounding["duration_ms"]
        nominal_power = grounding["power_kw"]
        duration = max(1, round(_sample_number(rng, nominal_duration, duration_bounds)))
        power = round(_sample_number(rng, nominal_power, power_bounds), 6)
        grounding["duration_ms"] = duration
        grounding["power_kw"] = power
        grounding["sampled_from"] = {
            "duration_ms": nominal_duration,
            "power_kw": nominal_power,
            "replicate": replicate,
        }
        for task in sampled.get("task_stream", []):
            if task.get("task_id") == grounding.get("task_id") and task.get("agent_id") == grounding.get("agent_id"):
                template = task.get("action_template")
                if template:
                    template["duration_ms"] = duration
                    template["power_kw"] = power
    sampled["calibration"] = {
        **calibration,
        "sampled_replicate": replicate,
        "sample_seed": seed,
    }
    return sampled


def calibration_manifest(episode: dict[str, Any]) -> dict[str, Any]:
    """Describe nominal values and synthetic ranges without sampling them."""
    calibration = episode.get("calibration", {})
    duration_bounds = list(calibration.get("duration_relative_range", DEFAULT_DURATION_RANGE))
    power_bounds = list(calibration.get("power_relative_range", DEFAULT_POWER_RANGE))
    actions = []
    for grounding in episode.get("action_grounding", []):
        actions.append({
            "agent_id": grounding.get("agent_id"),
            "task_id": grounding.get("task_id"),
            "target": grounding.get("target"),
            "operation": grounding.get("grounded_operation", grounding.get("operation")),
            "duration_ms_nominal": grounding.get("duration_ms"),
            "duration_relative_range": duration_bounds,
            "power_kw_nominal": grounding.get("power_kw"),
            "power_relative_range": power_bounds,
            "source": calibration.get("source", "synthetic_placeholder"),
        })
    return {
        "episode_id": episode.get("episode_id"),
        "calibration_status": calibration.get("status", "missing"),
        "actions": actions,
    }
