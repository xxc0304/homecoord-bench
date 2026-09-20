"""Parameterized variants for calibrating the seed task families."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def direct_conflict_variants(seed: dict[str, Any]) -> list[dict[str, Any]]:
    variants = []
    for visibility in ("policy_visible", "local_only"):
        for gap_ms in (0, 300, 1000):
            episode = deepcopy(seed)
            episode["base_episode_id"] = "HC-SEED-002"
            episode["episode_id"] = f"HC-VAR-002-{visibility}-{gap_ms}"
            episode["variant"] = {
                "family": "direct_device_conflict",
                "energy_visibility": visibility,
                "second_task_gap_ms": gap_ms,
            }
            episode["initial_state"]["values"]["devices"]["living_hvac"] = "cool_26"
            energy = next(agent for agent in episode["agents"] if agent["agent_id"] == "EnergyAgent")
            if visibility == "local_only":
                energy["observable_state"] = ["devices.living_hvac"]
                energy["constraint_visibility"] = "local"
                energy["policy_constraints"] = []
            else:
                energy["observable_state"] = ["devices.living_hvac", "request.comfort_active"]
                energy["constraint_visibility"] = "all"
            energy_task = next(task for task in episode["task_stream"] if task["task_id"] == "energy")
            energy_task["release_at_ms"] = gap_ms
            energy_task["goal"] = "reduce peak usage by turning off nonessential HVAC"
            variants.append(episode)
    return variants


def stale_action_variants(seed: dict[str, Any]) -> list[dict[str, Any]]:
    variants = []
    for enter_at_ms in (800, 1200, 1500, 1800, 2200):
        episode = deepcopy(seed)
        episode["base_episode_id"] = "HC-SEED-004"
        episode["episode_id"] = f"HC-VAR-004-enter-{enter_at_ms}"
        episode["variant"] = {"family": "stale_state_action", "resident_enter_at_ms": enter_at_ms}
        leave_at_ms = enter_at_ms + 3500
        episode["exogenous_events"][0]["at_ms"] = enter_at_ms
        episode["exogenous_events"][1]["at_ms"] = leave_at_ms
        care_task = next(task for task in episode["task_stream"] if task["task_id"] == "care")
        care_task["release_at_ms"] = enter_at_ms
        variants.append(episode)
    return variants


def indirect_conflict_variants(seed: dict[str, Any]) -> list[dict[str, Any]]:
    """Move the heating task across the known C2 overlap threshold."""
    variants = []
    for gap_ms in (0, 500, 1000, 1500, 2500):
        episode = deepcopy(seed)
        episode["base_episode_id"] = "HC-SEED-003"
        episode["episode_id"] = f"HC-VAR-003-gap-{gap_ms}"
        episode["variant"] = {
            "family": "indirect_environment_conflict",
            "second_task_gap_ms": gap_ms,
        }
        heat_task = next(task for task in episode["task_stream"] if task["task_id"] == "heat")
        heat_task["release_at_ms"] = gap_ms
        variants.append(episode)
    return variants


def resource_capacity_variants(seed: dict[str, Any]) -> list[dict[str, Any]]:
    """Sweep capacity around the 1.22 kW concurrent-action boundary."""
    variants = []
    for capacity_kw in (1.20, 1.21, 1.23, 8.0):
        episode = deepcopy(seed)
        episode["base_episode_id"] = "HC-SEED-001"
        capacity_label = str(capacity_kw).replace(".", "p")
        episode["episode_id"] = f"HC-VAR-001-cap-{capacity_label}"
        episode["variant"] = {
            "family": "resource_capacity_conflict",
            "capacity_kw": capacity_kw,
        }
        episode["home"]["resources"]["max_power_kw"] = capacity_kw
        capacity_rule = next(rule for rule in episode["conflict_rules"] if rule["type"] == "C3")
        capacity_rule["capacity"] = capacity_kw
        for task in episode["task_stream"]:
            task["release_at_ms"] = 0
        variants.append(episode)
    return variants
