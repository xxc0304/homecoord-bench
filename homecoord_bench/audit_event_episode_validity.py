"""Audit all episode JSON files against the event simulator's runtime contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from runtime.episode_validation import validate_event_episode


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULT = ROOT / "results" / "event_episode_validation_20260926.json"
EPISODE_DIRS = ("candidates", "pilot_pairs_v1", "pilot_physical_v2", "seeds")


def audit() -> dict[str, Any]:
    # Evidence matrices and derived sensor traces also live under data/, but
    # they are not benchmark episodes.  Keeping an explicit directory allowlist
    # prevents those artifacts from silently inflating episode counts.
    files = sorted(
        path
        for directory in EPISODE_DIRS
        for path in (DATA / directory).rglob("*.json")
        if path.name != "manifest.json"
    )
    records = []
    for path in files:
        episode_id = None
        try:
            episode = json.loads(path.read_text(encoding="utf-8"))
            episode_id = episode.get("episode_id") if isinstance(episode, dict) else None
            errors = validate_event_episode(episode)
        except (OSError, json.JSONDecodeError) as exc:
            errors = [f"could not load episode JSON: {exc}"]
        records.append({
            "path": path.relative_to(ROOT).as_posix(),
            "episode_id": episode_id,
            "valid": not errors,
            "errors": errors,
        })

    valid_count = sum(record["valid"] for record in records)
    return {
        "schema_version": "event-episode-validity-audit-0.1",
        "episode_count": len(records),
        "valid_count": valid_count,
        "invalid_count": len(records) - valid_count,
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RESULT)
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"},
                     ensure_ascii=False, indent=2))
