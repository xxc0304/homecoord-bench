"""Deduplicate three-channel co-activity found inside a pair-window review set."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


CHANNELS = ["Appliance2", "Appliance3", "Appliance4"]


def extract_bouts(
    summary_csv: Path,
    context_csv: Path,
    output_csv: Path,
    rows_csv: Path,
    output_json: Path,
    *,
    channels: list[str] = CHANNELS,
    house_id: str = "H5",
    threshold_w: float = 100,
    max_gap_seconds: int = 16,
) -> dict[str, Any]:
    with summary_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        summaries = {row["review_window_id"]: row for row in csv.DictReader(handle)}
    source_rows: dict[int, dict[str, str]] = {}
    candidate_memberships: dict[int, set[str]] = defaultdict(set)
    with context_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            line = int(row["source_csv_line"])
            existing = source_rows.get(line)
            if existing is not None:
                for column in ["Time", "Unix", "Aggregate", *channels, "Issues"]:
                    if existing[column] != row[column]:
                        raise ValueError(f"conflicting source values for CSV line {line}, column {column}")
            else:
                source_rows[line] = row
            if row["row_relation"] == "candidate_window":
                candidate_memberships[line].add(row["review_window_id"])

    triple_lines = [
        line
        for line, window_ids in candidate_memberships.items()
        if (source_rows[line]["Issues"] or "").strip() == "0"
        and all(float(source_rows[line][column]) >= threshold_w for column in channels)
        and window_ids
    ]
    triple_lines.sort(key=lambda line: (int(float(source_rows[line]["Unix"])), line))
    bouts: list[list[int]] = []
    current: list[int] = []
    previous_time: int | None = None
    for line in triple_lines:
        timestamp = int(float(source_rows[line]["Unix"]))
        if current and (line != current[-1] + 1 or previous_time is None or timestamp - previous_time > max_gap_seconds):
            bouts.append(current)
            current = []
        current.append(line)
        previous_time = timestamp
    if current:
        bouts.append(current)

    def classify_edge(adjacent_line: int, edge_line: int, *, start: bool) -> str:
        adjacent = source_rows.get(adjacent_line)
        edge = source_rows[edge_line]
        if adjacent is None:
            return "context_unavailable"
        adjacent_unix = int(float(adjacent["Unix"]))
        edge_unix = int(float(edge["Unix"]))
        gap = edge_unix - adjacent_unix if start else adjacent_unix - edge_unix
        if gap > max_gap_seconds:
            return "timestamp_gap_over_limit"
        if (adjacent["Issues"] or "").strip() != "0":
            return "Issues_nonzero"
        if any(float(adjacent[column]) < threshold_w for column in channels):
            return f"one_or_more_channels_below_{threshold_w:g}w"
        return "neighbor_still_triple_active"

    episode_rows: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    for index, lines in enumerate(bouts, start=1):
        bout_id = f"REFIT-{house_id}-TRIPLE-{threshold_w:g}W-{index:03d}"
        first = source_rows[lines[0]]
        last = source_rows[lines[-1]]
        first_time = int(float(first["Unix"]))
        last_time = int(float(last["Unix"]))
        gaps = [
            int(float(source_rows[right]["Unix"])) - int(float(source_rows[left]["Unix"]))
            for left, right in zip(lines, lines[1:])
        ]
        values = {column: [float(source_rows[line][column]) for line in lines] for column in channels}
        memberships = sorted({window_id for line in lines for window_id in candidate_memberships[line]})
        start_edge = classify_edge(lines[0] - 1, lines[0], start=True)
        end_edge = classify_edge(lines[-1] + 1, lines[-1], start=False)
        episode_rows.append(
            {
                "bout_id": bout_id,
                "start_time": first["Time"],
                "end_time": last["Time"],
                "source_csv_line_start": lines[0],
                "source_csv_line_end": lines[-1],
                "unique_source_rows": len(lines),
                "duration_estimate_seconds": last_time - first_time + 8,
                "max_adjacent_gap_seconds": max(gaps, default=0),
                "issues_flagged_rows_inside": sum((source_rows[line]["Issues"] or "").strip() != "0" for line in lines),
                "boundary_before_status": start_edge,
                "boundary_after_status": end_edge,
                "review_window_ids": ";".join(memberships),
                **{
                    f"{column}_min_median_max_w": json.dumps(
                        [min(values[column]), statistics.median(values[column]), max(values[column])]
                    )
                    for column in channels
                },
                "aggregate_min_median_max_w": json.dumps(
                    [
                        min(float(source_rows[line]["Aggregate"]) for line in lines),
                        statistics.median(float(source_rows[line]["Aggregate"]) for line in lines),
                        max(float(source_rows[line]["Aggregate"]) for line in lines),
                    ]
                ),
            }
        )
        for line in lines:
            row = source_rows[line]
            sample_rows.append(
                {
                    "bout_id": bout_id,
                    "source_csv_line": line,
                    "Time": row["Time"],
                    "Unix": row["Unix"],
                    "Aggregate": row["Aggregate"],
                    **{column: row[column] for column in channels},
                    "Issues": row["Issues"],
                    "review_window_ids": ";".join(sorted(candidate_memberships[line])),
                }
            )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(episode_rows[0]) if episode_rows else ["bout_id"])
        writer.writeheader()
        writer.writerows(episode_rows)
    with rows_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["bout_id", "source_csv_line", "Time", "Unix", "Aggregate", *channels, "Issues", "review_window_ids"],
        )
        writer.writeheader()
        writer.writerows(sample_rows)

    triple_occurrences = sum(
        1
        for line, window_ids in candidate_memberships.items()
        if (source_rows[line]["Issues"] or "").strip() == "0"
        and all(float(source_rows[line][column]) >= threshold_w for column in channels)
        for _ in window_ids
    )
    result = {
        "schema_version": "refit-triple-coactivity-bouts-0.2",
        "house_id": f"REFIT-{house_id}",
        "source_dataset": f"REFIT cleaned {house_id}, Zenodo DOI 10.5281/zenodo.5063428",
        "selection_scope": "Unique source rows inside the supplied pair-window review set; not a full-trace census.",
        "channels": channels,
        "threshold_w_all_three_channels": threshold_w,
        "issues_one_rows_excluded": True,
        "max_gap_seconds_within_bout": max_gap_seconds,
        "unique_source_rows_in_bouts": len(triple_lines),
        "duplicate_window_row_occurrences_before_deduplication": triple_occurrences,
        "bout_count": len(episode_rows),
        "bouts_at_least_300_seconds": sum(int(row["duration_estimate_seconds"]) >= 300 for row in episode_rows),
        "episodes_csv": str(output_csv),
        "source_rows_csv": str(rows_csv),
        "bouts": episode_rows,
        "interpretation_limits": [
            "These are same-row measured co-activity bouts across three monitored channels, deduplicated by source CSV line.",
            "The search is limited to source rows covered by the supplied pair-window review set; it is not a full-trace census.",
            "A bout does not identify user tasks, deadlines, appliance cycles, circuit capacity conflicts, or agent requests.",
            "REFIT sensors are not synchronized; publisher cleaning may include forward-filled or zero-filled intervals.",
            "A bout touching an Issues row at its boundary has uncertain exact onset/offset even when all rows inside the bout have Issues=0.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary_csv", type=Path)
    parser.add_argument("context_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("rows_csv", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--house-id", default="H5")
    parser.add_argument("--channel-a", default="Appliance2")
    parser.add_argument("--channel-b", default="Appliance3")
    parser.add_argument("--channel-c", default="Appliance4")
    parser.add_argument("--threshold-w", type=float, default=100)
    parser.add_argument("--max-gap-seconds", type=int, default=16)
    args = parser.parse_args()
    result = extract_bouts(
        args.summary_csv,
        args.context_csv,
        args.output_csv,
        args.rows_csv,
        args.output_json,
        channels=[args.channel_a, args.channel_b, args.channel_c],
        house_id=args.house_id,
        threshold_w=args.threshold_w,
        max_gap_seconds=args.max_gap_seconds,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "bouts"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
