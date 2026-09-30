"""Summarize the strict-boundary REFIT co-activity subset without task labels."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEVICE_COLUMNS = {"dryer": "Appliance2", "washer": "Appliance3", "dishwasher": "Appliance4"}


def _stats(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    return min(values), statistics.median(values), max(values)


def audit_subset(summary_csv: Path, context_csv: Path, output_csv: Path, output_json: Path) -> dict[str, Any]:
    with summary_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        all_summary = list(csv.DictReader(handle))
    summary = [row for row in all_summary if row["strict_clean_boundary_pair"] == "true"]
    if not summary:
        raise ValueError("no strict-boundary windows found in summary CSV")

    all_window_ids = {item["review_window_id"] for item in all_summary}
    context: dict[str, list[dict[str, str]]] = defaultdict(list)
    with context_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["review_window_id"] in all_window_ids:
                context[row["review_window_id"]].append(row)

    rows: list[dict[str, Any]] = []
    pair_counts: Counter[str] = Counter()
    triple_rows_total = candidate_rows_total = triple_bouts_total = windows_with_triple = 0
    durations: list[int] = []
    for item in summary:
        window_id = item["review_window_id"]
        device_pair = item["device_pair"]
        pair = device_pair.split("+")
        if len(pair) != 2 or any(device not in DEVICE_COLUMNS for device in pair):
            raise ValueError(f"unexpected device pair in {window_id}: {device_pair}")
        third_device = next(device for device in DEVICE_COLUMNS if device not in pair)
        columns = [DEVICE_COLUMNS[device] for device in pair]
        rows_for_window = sorted(context.get(window_id, []), key=lambda row: int(row["source_csv_line"]))
        candidate = [row for row in rows_for_window if row["row_relation"] == "candidate_window"]
        if len(candidate) != int(item["qualifying_rows"]):
            raise ValueError(f"candidate row count mismatch for {window_id}")

        timestamps = [int(float(row["Unix"])) for row in candidate]
        if any((row["Issues"] or "").strip() != "0" for row in candidate):
            raise ValueError(f"non-clear Issues row inside candidate {window_id}")
        if any(any(float(row[column]) < 100 for column in columns) for row in candidate):
            raise ValueError(f"selected pair falls below 100 W inside candidate {window_id}")
        if any(right - left > 16 for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError(f"timestamp gap above 16 seconds inside candidate {window_id}")

        pair_values = {column: [float(row[column]) for row in candidate] for column in columns}
        third_column = DEVICE_COLUMNS[third_device]
        third_values = [float(row[third_column]) for row in candidate]
        aggregate_values = [float(row["Aggregate"]) for row in candidate]
        triple_active = [all(float(row[column]) >= 100 for column in DEVICE_COLUMNS.values()) for row in candidate]
        triple_counts_by_threshold = {
            threshold: sum(all(float(row[column]) >= threshold for column in DEVICE_COLUMNS.values()) for row in candidate)
            for threshold in (50, 100, 300)
        }
        triple_rows = sum(triple_active)
        triple_bouts = 0
        previous_active = False
        previous_unix: int | None = None
        for row, active in zip(candidate, triple_active):
            timestamp = int(float(row["Unix"]))
            if active and (not previous_active or previous_unix is None or timestamp - previous_unix > 16):
                triple_bouts += 1
            previous_active = active
            previous_unix = timestamp

        pair_statistics = {column: _stats(values) for column, values in pair_values.items()}
        third_min, third_median, third_max = _stats(third_values)
        aggregate_min, aggregate_median, aggregate_max = _stats(aggregate_values)
        transitions = {
            column: sum(left != right for left, right in zip(values, values[1:]))
            for column, values in pair_values.items()
        }
        duration = int(item["duration_estimate_seconds"])
        durations.append(duration)
        candidate_rows_total += len(candidate)
        triple_rows_total += triple_rows
        triple_bouts_total += triple_bouts
        windows_with_triple += int(triple_rows > 0)
        pair_counts[device_pair] += 1

        output_row: dict[str, Any] = {
            "review_window_id": window_id,
            "device_pair": device_pair,
            "third_device": third_device,
            "start_time": item["start_time"],
            "end_time": item["end_time"],
            "duration_estimate_seconds": duration,
            "source_csv_line_start": item["source_csv_line_start"],
            "source_csv_line_end": item["source_csv_line_end"],
            "candidate_rows": len(candidate),
            "third_device_rows_ge_100w": sum(value >= 100 for value in third_values),
            "all_three_active_candidate_rows_ge_50w": triple_counts_by_threshold[50],
            "all_three_active_candidate_rows_ge_100w": triple_counts_by_threshold[100],
            "all_three_active_candidate_rows_ge_300w": triple_counts_by_threshold[300],
            "all_three_active_candidate_row_fraction_ge_100w": round(triple_rows / len(candidate), 4),
            "triple_active_bouts": triple_bouts,
            "aggregate_min_median_max_w": json.dumps([aggregate_min, aggregate_median, aggregate_max]),
            "context_issues_nonzero_count": item["context_issues_nonzero_count"],
            "context_gaps_over16_count": item["context_gaps_over16_count"],
            "start_boundary_status": item["start_boundary_status"],
            "end_boundary_status": item["end_boundary_status"],
            "pair_power_min_median_max_w": json.dumps(
                {device: pair_statistics[DEVICE_COLUMNS[device]] for device in pair}, ensure_ascii=False
            ),
            "pair_within_window_transitions": json.dumps(
                {device: transitions[DEVICE_COLUMNS[device]] for device in pair}, ensure_ascii=False
            ),
            "third_device_min_median_max_w": json.dumps([third_min, third_median, third_max]),
        }
        rows.append(output_row)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    strict_ids = {item["review_window_id"] for item in summary}
    triple_threshold_sensitivity: dict[str, Any] = {}
    for threshold in (50, 100, 300):
        all_occurrences: list[tuple[str, str]] = []
        strict_occurrences: list[tuple[str, str]] = []
        all_windows_with_activity = strict_windows_with_activity = 0
        for item in all_summary:
            window_id = item["review_window_id"]
            candidate = [row for row in context.get(window_id, []) if row["row_relation"] == "candidate_window"]
            active_source_lines = [
                row["source_csv_line"]
                for row in candidate
                if all(float(row[column]) >= threshold for column in DEVICE_COLUMNS.values())
            ]
            if active_source_lines:
                all_windows_with_activity += 1
                if window_id in strict_ids:
                    strict_windows_with_activity += 1
            all_occurrences.extend((window_id, line) for line in active_source_lines)
            if window_id in strict_ids:
                strict_occurrences.extend((window_id, line) for line in active_source_lines)
        triple_threshold_sensitivity[str(threshold)] = {
            "all_review_window_row_occurrences": len(all_occurrences),
            "all_unique_source_csv_rows": len({line for _, line in all_occurrences}),
            "all_review_windows_with_activity": all_windows_with_activity,
            "strict_subset_window_row_occurrences": len(strict_occurrences),
            "strict_subset_unique_source_csv_rows": len({line for _, line in strict_occurrences}),
            "strict_subset_windows_with_activity": strict_windows_with_activity,
        }

    result = {
        "schema_version": "refit-house5-strict-coactivity-subset-audit-0.1",
        "source_dataset": "REFIT cleaned House 5, Zenodo DOI 10.5281/zenodo.5063428",
        "source_files": {"summary_csv": str(summary_csv), "context_csv": str(context_csv)},
        "selection": "strict_clean_boundary_pair=true from the 100 W, Issues=0, max-gap-16-second review set",
        "strict_boundary_windows": len(summary),
        "windows_by_pair": dict(pair_counts),
        "candidate_rows": candidate_rows_total,
        "triple_active_candidate_row_occurrences_all_three_channels_ge_100w": triple_rows_total,
        "triple_active_candidate_row_occurrence_fraction_ge_100w": round(triple_rows_total / candidate_rows_total, 6),
        "windows_with_any_triple_active_row": windows_with_triple,
        "triple_active_bouts_inside_candidate_windows": triple_bouts_total,
        "all_three_channel_threshold_sensitivity_across_review_windows": triple_threshold_sensitivity,
        "candidate_duration_seconds_min_median_max": [min(durations), statistics.median(durations), max(durations)],
        "per_window_csv": str(output_csv),
        "interpretation_limits": [
            "This audit describes measured power co-activity in publisher-cleaned data; it does not label tasks, appliance cycles, circuit conflicts, or agent actions.",
            "REFIT channels are not synchronized and may include publisher-applied forward filling or zero filling.",
            "Threshold counts across review windows can repeat the same source CSV row when device-pair windows overlap; unique source-row counts are reported separately.",
            "All-three-channel activity is a thresholded same-row observation, not evidence that three independent user tasks were requested.",
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
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_subset(args.summary_csv, args.context_csv, args.output_csv, args.output_json), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
