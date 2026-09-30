"""Flag episodes whose initial or exogenous-only state satisfies all goals."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_RESULT = ROOT / "results" / "external_goal_credit_audit_20260927.json"
EPISODE_DIRS = ("candidates", "pilot_pairs_v1", "pilot_physical_v2", "seeds")
sys.path.insert(0, str(ROOT))

from evaluate import goals_satisfied, set_path  # noqa: E402


def _patch(state: dict[str, Any], patch: dict[str, Any]) -> None:
    for path, value in patch.items():
        set_path(state, path, deepcopy(value))


def audit() -> dict[str, Any]:
    records = []
    files = sorted(
        path
        for directory in EPISODE_DIRS
        for path in (DATA / directory).rglob("*.json")
        if path.name != "manifest.json"
    )
    for path in files:
        try:
            episode = json.loads(path.read_text(encoding="utf-8"))
            goals = episode.get("goals", [])
            state = deepcopy(episode.get("initial_state", {}).get("values", {}))
            initially_satisfied = bool(goals) and goals_satisfied(state, goals)
            event_success = None
            for event in sorted(episode.get("exogenous_events", []), key=lambda item: item["at_ms"]):
                _patch(state, event.get("patch", {}))
                if goals and goals_satisfied(state, goals):
                    event_success = {
                        "at_ms": event["at_ms"],
                        "event": event.get("event", "unspecified"),
                        "goal_paths": [goal["path"] for goal in goals],
                    }
                    break
            errors = []
            episode_id = episode.get("episode_id")
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            episode_id = None
            initially_satisfied = False
            event_success = None
            errors = [f"could not audit episode: {exc}"]

        records.append({
            "path": path.relative_to(ROOT).as_posix(),
            "episode_id": episode_id,
            "initial_state_satisfies_goals": initially_satisfied,
            "exogenous_event_prefix_satisfies_goals": event_success is not None,
            "environment_only_goal_success": initially_satisfied or event_success is not None,
            "first_event_only_success": event_success,
            "errors": errors,
        })

    return {
        "schema_version": "external-goal-credit-audit-0.1",
        "episode_count": len(records),
        "initial_state_goal_success_count": sum(record["initial_state_satisfies_goals"] for record in records),
        "event_only_goal_success_count": sum(record["exogenous_event_prefix_satisfies_goals"] for record in records),
        "environment_only_goal_success_count": sum(record["environment_only_goal_success"] for record in records),
        "error_count": sum(bool(record["errors"]) for record in records),
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"},
                     ensure_ascii=False, indent=2))
