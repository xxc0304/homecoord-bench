"""Annotate candidate episodes with explicit synthetic range assumptions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT


def annotate(candidates_dir: Path) -> int:
    count = 0
    for path in sorted(candidates_dir.glob("*.json")):
        episode = json.loads(path.read_text(encoding="utf-8"))
        episode["calibration"] = {
            "status": "synthetic_range",
            "source": "derived_from_nominal_placeholder",
            "duration_relative_range": [0.80, 1.20],
            "power_relative_range": [0.85, 1.15],
            "event_jitter_ms": 0,
            "notes": "Robustness assumptions only; replace with simulator/device traces before physical claims.",
        }
        path.write_text(json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-dir", type=Path, default=ROOT / "data" / "candidates")
    args = parser.parse_args()
    print(json.dumps({"annotated_episodes": annotate(args.candidates_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
