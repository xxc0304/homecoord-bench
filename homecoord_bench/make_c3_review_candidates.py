"""Build paired, review-only C3 episodes from the two non-nested templates."""

from __future__ import annotations

import hashlib
import itertools
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_structural_generalization import make_episode_from_specs
from runtime.episode_validation import validate_event_episode


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "revision_drafts" / "20260929_c3_non_nested_review"
PRESSURES = (0.8, 1.0, 1.2, 1.6)


def make_candidates() -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for template_id, specs in TEMPLATES.items():
        for pressure in PRESSURES:
            episode = make_episode_from_specs(template_id, specs, pressure)
            episode["source_type"] = "controlled_review_candidate_e2_ratings_e4_workloads"
            episode["review_status"] = "proposed_revision_not_scored"
            episode["resource_pressure"]["interpretation"] = (
                "sum of nameplate or connection ratings divided by a controlled "
                "managed power budget"
            )
            episode["scenario_assumptions"].update({
                "power_semantics": (
                    "conservative rated-power reservation for full configured cycle; "
                    "not measured instantaneous consumption"
                ),
                "capacity_semantics": (
                    "controlled managed-load budget, not an asserted household "
                    "service or circuit rating"
                ),
                "physical_calibration": "rated-power envelope only; time-varying load unavailable",
                "review_gate": "requires two independent blinded reviewers before freeze",
            })
            episodes.append(episode)
    return episodes


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _without_factor(episode: dict[str, Any]) -> dict[str, Any]:
    copy = deepcopy(episode)
    copy.pop("episode_id")
    copy["home"]["resources"].pop("max_power_kw")
    copy["conflict_rules"][0].pop("capacity")
    copy.pop("resource_pressure")
    return copy


def feasible_schedule(episode: dict[str, Any]) -> list[dict[str, int | str]] | None:
    """Exact ideal schedule for these common-release, fixed-load C3 candidates.

    Enumerate every start order. For a fixed order, placing each job at its
    earliest resource-feasible time dominates placing it later because all jobs
    are already released. This ignores proposal and command latency on purpose:
    it checks whether the task design itself is physically schedulable.
    """
    tasks = episode["task_stream"]
    releases = {int(task["release_at_ms"]) for task in tasks}
    if len(releases) != 1:
        raise ValueError("feasibility oracle only supports common-release candidates")
    release = releases.pop()
    capacity = float(episode["home"]["resources"]["max_power_kw"])
    for order in itertools.permutations(tasks):
        scheduled: list[dict[str, int | str | float]] = []
        for task in order:
            power = float(task["action_template"]["power_kw"])
            duration = int(task["action_template"]["duration_ms"])
            deadline = int(task["completion_deadline_ms"])
            # Existing jobs can only release capacity at their finish times.
            candidate_times = sorted({release, *(int(job["finish_ms"]) for job in scheduled)})
            def fits(time: int) -> bool:
                finish = time + duration
                points = {time}
                points.update(int(job["start_ms"]) for job in scheduled
                              if time < int(job["start_ms"]) < finish)
                return all(sum(float(job["power_kw"]) for job in scheduled
                               if int(job["start_ms"]) <= point < int(job["finish_ms"]))
                           + power <= capacity + 1e-9 for point in points)

            start = next((time for time in candidate_times
                          if time >= release and fits(time)), None)
            if start is None or start + duration > deadline:
                break
            scheduled.append({"task_id": task["task_id"], "start_ms": start,
                              "finish_ms": start + duration, "power_kw": power})
        else:
            return [{key: job[key] for key in ("task_id", "start_ms", "finish_ms")}
                    for job in scheduled]
    return None


def audit(episodes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(episodes) != len(TEMPLATES) * len(PRESSURES):
        errors.append("candidate count mismatch")
    for episode in episodes:
        errors.extend(f"{episode['episode_id']}: {error}"
                      for error in validate_event_episode(episode))
        powers = [float(task["action_template"]["power_kw"])
                  for task in episode["task_stream"]]
        cap = float(episode["home"]["resources"]["max_power_kw"])
        if max(powers) > cap:
            errors.append(f"{episode['episode_id']}: individual task exceeds budget")
        elif feasible_schedule(episode) is None:
            errors.append(f"{episode['episode_id']}: no ideal all-deadline schedule")
        if abs(sum(powers) / cap - episode["resource_pressure"]["load_to_capacity_ratio"]) > 1e-5:
            errors.append(f"{episode['episode_id']}: pressure mismatch")
        if episode["review_status"] != "proposed_revision_not_scored":
            errors.append(f"{episode['episode_id']}: incorrect review status")
    for template_id in TEMPLATES:
        group = [episode for episode in episodes
                 if episode["base_episode_id"] == f"HC-C3-{template_id}"]
        if len(group) != len(PRESSURES):
            errors.append(f"{template_id}: incomplete paired group")
        elif any(_without_factor(item) != _without_factor(group[0]) for item in group[1:]):
            errors.append(f"{template_id}: pair differs beyond capacity factor")
    return errors


def generate(output: Path = OUTPUT) -> dict[str, Any]:
    episodes = make_candidates()
    errors = audit(episodes)
    if errors:
        raise ValueError(errors)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for episode in episodes:
        name = f"{episode['episode_id']}.json"
        (output / name).write_text(
            json.dumps(episode, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        files.append({"file": name, "canonical_sha256": canonical_hash(episode)})
    manifest = {
        "schema_version": "homecoord-c3-review-candidates-0.1",
        "status": "author_side_review_candidates_not_frozen",
        "template_count": len(TEMPLATES),
        "episode_configurations": len(episodes),
        "pressure_levels": list(PRESSURES),
        "pair_variable": "managed shared power budget only",
        "ideal_feasibility_scope": "exact common-release, nonpreemptive fixed-load schedule; zero proposal and command latency",
        "ideal_feasible_schedules": {
            episode["episode_id"]: feasible_schedule(episode) for episode in episodes
        },
        "power_interpretation": "rated-power envelope held for full configured cycle",
        "review_required": [
            "two independent blinded judgments of task plausibility and conflict label",
            "whether full-cycle rated-power reservation is an acceptable benchmark abstraction",
            "whether service deadlines and cycles have adequate slack and naturalness",
        ],
        "files": files,
        "audit": {"status": "pass", "errors": []},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(generate(), ensure_ascii=False, indent=2))
