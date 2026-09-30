"""Create a paired C3 batch using normalized load-to-capacity pressure.

The capacity values are controlled benchmark factors. They are not asserted to
be the service capacity of a representative household.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_c3_three_load import make_episode


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "revision_drafts" / "20260928_normalized_c3"
TOTAL_NOMINAL_POWER_KW = 5.7
CONDITIONS = (
    ("CLEAR-MARGIN", 0.8),
    ("EXACT-BOUNDARY", 1.0),
    ("MODERATE-OVERLOAD", 1.2),
    ("SEVERE-OVERLOAD", TOTAL_NOMINAL_POWER_KW / 3.5),
)


def make_condition(name: str, pressure_ratio: float) -> dict[str, Any]:
    episode = deepcopy(make_episode("control"))
    capacity = round(TOTAL_NOMINAL_POWER_KW / pressure_ratio, 6)
    episode["episode_id"] = f"HC-PAIR-C3-NORMALIZED-{name}"
    episode["base_episode_id"] = "HC-PAIR-C3-NORMALIZED"
    episode["source_type"] = "controlled_normalized_capacity_draft"
    episode["review_status"] = "proposed_revision_not_scored"
    episode["home"]["resources"]["max_power_kw"] = capacity
    episode["conflict_rules"] = [{"type": "C3", "capacity": capacity}]
    episode["resource_pressure"] = {
        "capacity_semantics": "managed_shared_power_budget",
        "capacity_kw": capacity,
        "sum_nominal_requested_power_kw": TOTAL_NOMINAL_POWER_KW,
        "load_to_capacity_ratio": round(TOTAL_NOMINAL_POWER_KW / capacity, 6),
        "condition": name.lower().replace("-", "_"),
        "source": "controlled_benchmark_factor",
        "population_representativeness": "not_claimed",
    }
    episode["scenario_assumptions"].update({
        "power_source": (
            "controlled managed-power budget; no claim that this is a breaker, "
            "utility service rating, or representative household capacity"
        ),
        "capacity_design": (
            "capacity derived from fixed total nominal requested load divided by "
            "the predeclared load-to-capacity pressure ratio"
        ),
        "formal_use": "synthetic mechanism and scheduling stress subset",
    })
    return episode


def _without_capacity(episode: dict[str, Any]) -> dict[str, Any]:
    copy = deepcopy(episode)
    copy.pop("episode_id", None)
    copy.pop("resource_pressure", None)
    copy["home"]["resources"].pop("max_power_kw", None)
    copy["conflict_rules"] = [{"type": "C3"}]
    copy["scenario_assumptions"].pop("capacity_design", None)
    return copy


def audit(episodes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(episodes) != len(CONDITIONS):
        errors.append("condition count mismatch")
    references = [_without_capacity(episode) for episode in episodes]
    if any(reference != references[0] for reference in references[1:]):
        errors.append("conditions differ in fields other than capacity metadata")
    ratios = [episode["resource_pressure"]["load_to_capacity_ratio"] for episode in episodes]
    expected = [round(ratio, 6) for _, ratio in CONDITIONS]
    if ratios != expected:
        errors.append(f"pressure ratios differ: expected {expected}, got {ratios}")
    for episode in episodes:
        capacity = episode["home"]["resources"]["max_power_kw"]
        powers = [task["action_template"]["power_kw"] for task in episode["task_stream"]]
        if any(power > capacity for power in powers):
            errors.append(f"{episode['episode_id']}: an individual task exceeds capacity")
        if abs(sum(powers) - TOTAL_NOMINAL_POWER_KW) > 1e-9:
            errors.append(f"{episode['episode_id']}: total power drifted")
    return errors


def generate(output: Path = OUTPUT) -> dict[str, Any]:
    episodes = [make_condition(name, ratio) for name, ratio in CONDITIONS]
    errors = audit(episodes)
    if errors:
        raise ValueError(errors)
    output.mkdir(parents=True, exist_ok=True)
    for episode in episodes:
        (output / f"{episode['episode_id']}.json").write_text(
            json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    manifest = {
        "schema_version": "homecoord-c3-normalized-capacity-batch-0.1",
        "status": "proposed_revision_not_scored",
        "base_template": "c3_three_load_v0.1",
        "fixed_total_nominal_power_kw": TOTAL_NOMINAL_POWER_KW,
        "capacity_semantics": "managed_shared_power_budget",
        "conditions": [episode["resource_pressure"] for episode in episodes],
        "files": [f"{episode['episode_id']}.json" for episode in episodes],
        "claims_allowed": [
            "controlled effect of load-to-capacity pressure on coordination behavior",
            "paired safety-service-deadline-latency comparison",
        ],
        "claims_not_allowed": [
            "representative household capacity or conflict frequency",
            "measured appliance cycle power or deadline distribution",
        ],
        "audit": {"status": "pass", "errors": errors},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(generate(), ensure_ascii=False, indent=2))
