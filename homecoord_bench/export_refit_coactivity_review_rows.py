"""Export source CSV rows around a REFIT co-activity review set for inspection."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def export_review_rows(
    source: Path,
    review_json: Path,
    output: Path,
    *,
    context_rows: int,
    summary_output: Path | None = None,
) -> dict[str, Any]:
    if context_rows < 0:
        raise ValueError("context_rows must be non-negative")
    review = json.loads(review_json.read_text(encoding="utf-8"))
    windows = review.get("windows", [])
    if not windows:
        raise ValueError("review set contains no windows")
    threshold_w = float(review["selection"]["threshold_w"])
    max_gap_seconds = float(review["selection"]["max_gap_seconds_within_window"])
    device_columns = review.get("selection", {}).get(
        "device_columns", {"dryer": "Appliance2", "washer": "Appliance3", "dishwasher": "Appliance4"}
    )
    candidate_counts = {window["window_id"]: 0 for window in windows}
    previous_candidate_unix: dict[str, int] = {}
    boundary_rows = {window["window_id"]: {} for window in windows}
    context_issue_counts = {window["window_id"]: 0 for window in windows}
    context_gap_counts = {window["window_id"]: 0 for window in windows}
    previous_range_unix: dict[str, int] = {}

    ranges: list[dict[str, Any]] = []
    for window in windows:
        first = int(window["source_csv_line_start"])
        last = int(window["source_csv_line_end"])
        ranges.append(
            {
                "window_id": window["window_id"],
                "pair": "+".join(window["pair"]),
                "first": max(2, first - context_rows),
                "last": last + context_rows,
                "candidate_first": first,
                "candidate_last": last,
            }
        )
    ranges.sort(key=lambda item: (item["first"], item["last"], item["window_id"]))

    output.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "review_window_id",
        "device_pair",
        "row_relation",
        "source_csv_line",
        "Time",
        "Unix",
        "Aggregate",
        *dict.fromkeys(device_columns.values()),
        "Issues",
    ]
    emitted = 0
    with source.open("r", encoding="utf-8-sig", newline="") as input_handle, output.open(
        "w", encoding="utf-8-sig", newline=""
    ) as output_handle:
        reader = csv.DictReader(input_handle)
        missing = sorted(set(columns[4:]) - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"source CSV missing columns: {missing}")
        writer = csv.DictWriter(output_handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        next_range = 0
        active_ranges: dict[int, dict[str, Any]] = {}
        for line_number, row in enumerate(reader, start=2):
            while next_range < len(ranges) and ranges[next_range]["first"] <= line_number:
                active_ranges[next_range] = ranges[next_range]
                next_range += 1
            for index in [index for index, item in active_ranges.items() if item["last"] < line_number]:
                del active_ranges[index]
            for item in active_ranges.values():
                window_id = item["window_id"]
                relation = (
                    "candidate_window"
                    if item["candidate_first"] <= line_number <= item["candidate_last"]
                    else "context_before"
                    if line_number < item["candidate_first"]
                    else "context_after"
                )
                if relation == "context_before":
                    if line_number == item["candidate_first"] - 1:
                        boundary_rows[window_id]["before"] = dict(row)
                    if (row["Issues"] or "").strip() != "0":
                        context_issue_counts[window_id] += 1
                elif relation == "context_after":
                    if line_number == item["candidate_last"] + 1:
                        boundary_rows[window_id]["after"] = dict(row)
                    if (row["Issues"] or "").strip() != "0":
                        context_issue_counts[window_id] += 1
                elif (row["Issues"] or "").strip() != "0":
                    context_issue_counts[window_id] += 1

                timestamp = int(float(row["Unix"]))
                if window_id in previous_range_unix and timestamp - previous_range_unix[window_id] > max_gap_seconds:
                    context_gap_counts[window_id] += 1
                previous_range_unix[window_id] = timestamp

                if relation == "candidate_window":
                    if line_number == item["candidate_first"]:
                        boundary_rows[window_id]["first"] = dict(row)
                    if line_number == item["candidate_last"]:
                        boundary_rows[window_id]["last"] = dict(row)
                    if (row["Issues"] or "").strip() != "0":
                        raise ValueError(f"candidate {window_id} contains a non-clear Issues row at line {line_number}")
                    for device in item["pair"].split("+"):
                        if float(row[device_columns[device]]) < threshold_w:
                            raise ValueError(f"candidate {window_id} falls below {threshold_w} W at line {line_number}")
                    timestamp = int(float(row["Unix"]))
                    if window_id in previous_candidate_unix and timestamp - previous_candidate_unix[window_id] > max_gap_seconds:
                        raise ValueError(f"candidate {window_id} exceeds the selected timestamp gap at line {line_number}")
                    previous_candidate_unix[window_id] = timestamp
                    candidate_counts[window_id] += 1
                writer.writerow(
                    {
                        "review_window_id": item["window_id"],
                        "device_pair": item["pair"],
                        "row_relation": relation,
                        "source_csv_line": line_number,
                        **row,
                    }
                )
                emitted += 1
        last_source_line = line_number if "line_number" in locals() else 1
        if last_source_line < max(item["last"] for item in ranges):
            raise ValueError(
                f"source CSV ended at line {last_source_line}, before requested context line "
                f"{max(item['last'] for item in ranges)}"
            )
    for window in windows:
        window_id = window["window_id"]
        expected_lines = int(window["source_csv_line_end"]) - int(window["source_csv_line_start"]) + 1
        if candidate_counts[window_id] != int(window["qualifying_rows"]) or candidate_counts[window_id] != expected_lines:
            raise ValueError(
                f"candidate {window_id} row-count mismatch: exported {candidate_counts[window_id]}, "
                f"JSON qualifying_rows {window['qualifying_rows']}, line span {expected_lines}"
            )

    if summary_output is not None:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_columns = [
            "review_window_id",
            "device_pair",
            "start_time",
            "end_time",
            "duration_estimate_seconds",
            "source_csv_line_start",
            "source_csv_line_end",
            "qualifying_rows",
            "mean_power_w_by_device",
            "peak_pair_power_w",
            "peak_all_three_power_w",
            "start_boundary_status",
            "end_boundary_status",
            "strict_clean_boundary_pair",
            "context_issues_nonzero_count",
            "context_gaps_over16_count",
            "review_status",
            "review_reason",
            "reviewer_notes",
        ]
        with summary_output.open("w", encoding="utf-8-sig", newline="") as summary_handle:
            writer = csv.DictWriter(summary_handle, fieldnames=summary_columns)
            writer.writeheader()
            for window in windows:
                window_id = window["window_id"]
                pair_columns = [device_columns[device] for device in window["pair"]]
                boundary = boundary_rows[window_id]

                def classify_boundary(adjacent_row: dict[str, str] | None, edge_row: dict[str, str] | None, *, start: bool) -> str:
                    if adjacent_row is None or edge_row is None:
                        return "no_adjacent_context"
                    adjacent_unix = int(float(adjacent_row["Unix"]))
                    edge_unix = int(float(edge_row["Unix"]))
                    gap = edge_unix - adjacent_unix if start else adjacent_unix - edge_unix
                    if gap > max_gap_seconds:
                        return "timestamp_gap_over_16s"
                    if (adjacent_row["Issues"] or "").strip() != "0":
                        return "Issues_nonzero"
                    if any(float(adjacent_row[column]) < threshold_w for column in pair_columns):
                        return "clean_below_threshold"
                    return "unexpectedly_active_neighbor"

                start_status = classify_boundary(boundary.get("before"), boundary.get("first"), start=True)
                end_status = classify_boundary(boundary.get("after"), boundary.get("last"), start=False)
                writer.writerow(
                    {
                        **{key: window.get(key) for key in summary_columns[:8]},
                        "review_window_id": window_id,
                        "device_pair": "+".join(window["pair"]),
                        "mean_power_w_by_device": json.dumps(
                            window["mean_power_w_by_device"], ensure_ascii=False, sort_keys=True
                        ),
                        "peak_pair_power_w": window["peak_pair_power_w"],
                        "peak_all_three_power_w": window["peak_all_three_power_w"],
                        "start_boundary_status": start_status,
                        "end_boundary_status": end_status,
                        "strict_clean_boundary_pair": str(
                            start_status == "clean_below_threshold" and end_status == "clean_below_threshold"
                        ).lower(),
                        "context_issues_nonzero_count": context_issue_counts[window_id],
                        "context_gaps_over16_count": context_gap_counts[window_id],
                        "review_status": "",
                        "review_reason": "",
                        "reviewer_notes": "",
                    }
                )

    return {
        "review_windows": len(windows),
        "context_rows_each_side": context_rows,
        "exported_rows": emitted,
        "candidate_window_consistency_checks": "passed",
        "output": str(output),
        "summary_output": str(summary_output) if summary_output is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("review_json", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--context-rows", type=int, default=30)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            export_review_rows(
                args.source,
                args.review_json,
                args.output,
                context_rows=args.context_rows,
                summary_output=args.summary_output,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
