"""Screen every three-channel combination in a REFIT trace.

This is an observational power-coactivity audit. Publisher-flagged rows and
timestamp gaps over the configured limit break bouts. Appliance channel labels
are deliberately left uninterpreted unless separately verified by the dataset
publisher.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_CHANNELS = [f"Appliance{i}" for i in range(1, 10)]
DEFAULT_THRESHOLDS = [50, 100, 300]


def scan_trace(
    source: Path,
    output_csv: Path,
    output_json: Path,
    *,
    channels: list[str] = DEFAULT_CHANNELS,
    thresholds: list[float] = DEFAULT_THRESHOLDS,
    timestamp_column: str = "Unix",
    quality_column: str = "Issues",
    expected_interval_seconds: int = 8,
    max_gap_seconds: int = 16,
    source_sha256: str | None = None,
    source_md5: str | None = None,
    min_export_duration_seconds: int = 60,
) -> dict[str, Any]:
    """Find all contiguous same-row three-channel threshold co-activity bouts."""
    if len(channels) < 3 or len(set(channels)) != len(channels):
        raise ValueError("at least three unique channels are required")
    if not thresholds or any(value <= 0 for value in thresholds):
        raise ValueError("thresholds must be positive")
    all_combos = list(itertools.combinations(channels, 3))
    # Per threshold, only currently-active triples are retained, keeping the
    # pass linear in rows plus the triples active in each sample.
    active: dict[float, dict[tuple[str, ...], dict[str, Any]]] = {
        threshold: {} for threshold in thresholds
    }
    bouts: list[dict[str, Any]] = []
    bout_counters: Counter[tuple[float, tuple[str, ...]]] = Counter()
    qualifying_rows: Counter[tuple[float, tuple[str, ...]]] = Counter()
    unique_active_source_rows: Counter[float] = Counter()
    row_count = clear_rows = flagged_rows = invalid_flag_rows = 0
    gap_count = 0
    previous_unix: int | None = None
    previous_clear = False
    previous_active_channels: dict[float, set[str]] = {threshold: set() for threshold in thresholds}

    def close(threshold: float, combo: tuple[str, ...], reason: str) -> None:
        state = active[threshold].pop(combo, None)
        if state is None:
            return
        duration = state["last_unix"] - state["start_unix"] + expected_interval_seconds
        bout_counters[(threshold, combo)] += 1
        bout_id = (
            f"REFIT-H3-TRI-{combo[0]}-{combo[1]}-{combo[2]}-"
            f"{threshold:g}W-{bout_counters[(threshold, combo)]:04d}"
        )
        bouts.append(
            {
                "bout_id": bout_id,
                "threshold_w": threshold,
                "channels": list(combo),
                "start_time": state["start_time"],
                "end_time": state["last_time"],
                "start_unix": state["start_unix"],
                "end_unix": state["last_unix"],
                "source_csv_line_start": state["line_start"],
                "source_csv_line_end": state["line_end"],
                "qualifying_rows": state["rows"],
                "duration_estimate_seconds": duration,
                "max_adjacent_gap_seconds": state["max_gap"],
                "boundary_before_status": state["boundary_before"],
                "boundary_after_status": reason,
                "channel_min_mean_max_w": {
                    channel: [
                        state["power_min"][channel],
                        round(state["power_sum"][channel] / state["rows"], 3),
                        state["power_max"][channel],
                    ]
                    for channel in combo
                },
            }
        )

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted({timestamp_column, quality_column, *channels} - fieldnames)
        if missing:
            raise ValueError(f"missing columns: {missing}")

        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            try:
                timestamp = int(float(row[timestamp_column]))
            except (TypeError, ValueError):
                raise ValueError(f"invalid timestamp on CSV line {line_number}") from None
            if previous_unix is not None and timestamp <= previous_unix:
                raise ValueError(f"non-monotonic timestamp on CSV line {line_number}")
            gap = timestamp - previous_unix if previous_unix is not None else None
            gap_break = gap is not None and gap > max_gap_seconds
            if gap_break:
                gap_count += 1
                for threshold in thresholds:
                    for combo in list(active[threshold]):
                        close(threshold, combo, "timestamp_gap_over_limit")

            flag = (row[quality_column] or "").strip()
            if flag != "0":
                if flag == "1":
                    flagged_rows += 1
                else:
                    invalid_flag_rows += 1
                for threshold in thresholds:
                    for combo in list(active[threshold]):
                        close(threshold, combo, "Issues_nonzero")
                    previous_active_channels[threshold] = set()
                previous_clear = False
                previous_unix = timestamp
                continue

            clear_rows += 1
            try:
                watts = {channel: float(row[channel]) for channel in channels}
            except (TypeError, ValueError):
                raise ValueError(f"invalid channel power on CSV line {line_number}") from None
            if any(value < 0 for value in watts.values()):
                raise ValueError(f"negative channel power on CSV line {line_number}")

            for threshold in thresholds:
                active_channels = {channel for channel, power in watts.items() if power >= threshold}
                current_combos = set(itertools.combinations(sorted(active_channels), 3))
                if current_combos:
                    unique_active_source_rows[threshold] += 1
                for combo in set(active[threshold]) - current_combos:
                    close(threshold, combo, "one_or_more_channels_below_threshold")
                if current_combos:
                    for combo in current_combos:
                        qualifying_rows[(threshold, combo)] += 1
                        state = active[threshold].get(combo)
                        if state is None:
                            if gap_break:
                                boundary_before = "timestamp_gap_over_limit"
                            elif not previous_clear:
                                boundary_before = "Issues_nonzero" if row_count > 1 else "trace_start"
                            elif not set(combo).issubset(previous_active_channels[threshold]):
                                boundary_before = "one_or_more_channels_below_threshold"
                            else:
                                boundary_before = "trace_start"
                            active[threshold][combo] = {
                                "start_time": row.get("Time", ""),
                                "last_time": row.get("Time", ""),
                                "start_unix": timestamp,
                                "last_unix": timestamp,
                                "line_start": line_number,
                                "line_end": line_number,
                                "rows": 1,
                                "max_gap": 0,
                                "boundary_before": boundary_before,
                                "power_sum": {channel: watts[channel] for channel in combo},
                                "power_min": {channel: watts[channel] for channel in combo},
                                "power_max": {channel: watts[channel] for channel in combo},
                            }
                        else:
                            state["last_time"] = row.get("Time", "")
                            state["last_unix"] = timestamp
                            state["line_end"] = line_number
                            state["rows"] += 1
                            state["max_gap"] = max(state["max_gap"], gap or 0)
                            for channel in combo:
                                value = watts[channel]
                                state["power_sum"][channel] += value
                                state["power_min"][channel] = min(state["power_min"][channel], value)
                                state["power_max"][channel] = max(state["power_max"][channel], value)
                previous_active_channels[threshold] = active_channels

            previous_clear = True
            previous_unix = timestamp

    for threshold in thresholds:
        for combo in list(active[threshold]):
            close(threshold, combo, "trace_end")

    bouts.sort(key=lambda item: (item["threshold_w"], item["start_unix"], item["channels"]))
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "bout_id", "threshold_w", "channels", "start_time", "end_time", "start_unix", "end_unix",
        "source_csv_line_start", "source_csv_line_end", "qualifying_rows", "duration_estimate_seconds",
        "max_adjacent_gap_seconds", "boundary_before_status", "boundary_after_status", "channel_min_mean_max_w",
    ]
    exported_bouts = [bout for bout in bouts if bout["duration_estimate_seconds"] >= min_export_duration_seconds]
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for bout in exported_bouts:
            writer.writerow({**bout, "channels": "+".join(bout["channels"]), "channel_min_mean_max_w": json.dumps(bout["channel_min_mean_max_w"], ensure_ascii=False)})

    combo_summaries = []
    for threshold in thresholds:
        for combo in all_combos:
            matching = [bout for bout in bouts if bout["threshold_w"] == threshold and tuple(bout["channels"]) == combo]
            durations = [bout["duration_estimate_seconds"] for bout in matching]
            combo_summaries.append(
                {
                    "threshold_w": threshold,
                    "channels": list(combo),
                    "qualifying_sample_rows": qualifying_rows[(threshold, combo)],
                    "bout_count": len(matching),
                    "bouts_at_least_60_seconds": sum(value >= 60 for value in durations),
                    "bouts_at_least_300_seconds": sum(value >= 300 for value in durations),
                    "bouts_at_least_1800_seconds": sum(value >= 1800 for value in durations),
                    "duration_seconds_min_median_p90_max": (
                        [min(durations), statistics.median(durations), sorted(durations)[int(0.9 * (len(durations) - 1))], max(durations)]
                        if durations else None
                    ),
                    "both_boundaries_are_clear_threshold_crossings": sum(
                        bout["boundary_before_status"] == "one_or_more_channels_below_threshold"
                        and bout["boundary_after_status"] == "one_or_more_channels_below_threshold"
                        for bout in matching
                    ),
                }
            )
    by_threshold = {}
    for threshold in thresholds:
        subset = [item for item in combo_summaries if item["threshold_w"] == threshold]
        threshold_bouts = [bout for bout in bouts if bout["threshold_w"] == threshold]
        durations = [bout["duration_estimate_seconds"] for bout in threshold_bouts]
        clear_boundary_bouts = [
            bout
            for bout in threshold_bouts
            if bout["boundary_before_status"] == "one_or_more_channels_below_threshold"
            and bout["boundary_after_status"] == "one_or_more_channels_below_threshold"
        ]
        ranked = sorted(
            subset,
            key=lambda item: (-item["bouts_at_least_300_seconds"], -item["qualifying_sample_rows"], item["channels"]),
        )
        by_threshold[str(threshold)] = {
            "channel_triple_sample_row_occurrences": sum(item["qualifying_sample_rows"] for item in subset),
            "unique_source_rows_with_any_qualifying_triple": unique_active_source_rows[threshold],
            "triples_with_any_qualifying_rows": sum(item["qualifying_sample_rows"] > 0 for item in subset),
            "bout_count_across_triples": len(threshold_bouts),
            "bouts_at_least_60_seconds": sum(value >= 60 for value in durations),
            "bouts_at_least_300_seconds": sum(value >= 300 for value in durations),
            "bouts_at_least_1800_seconds": sum(value >= 1800 for value in durations),
            "bouts_with_both_clear_threshold_boundaries": len(clear_boundary_bouts),
            "bouts_at_least_300_seconds_with_both_clear_threshold_boundaries": sum(
                bout["duration_estimate_seconds"] >= 300 for bout in clear_boundary_bouts
            ),
            "duration_seconds_min_median_p90_max": (
                [min(durations), statistics.median(durations), sorted(durations)[int(0.9 * (len(durations) - 1))], max(durations)]
                if durations else None
            ),
            "triples_ranked_by_300s_bouts_then_rows": ranked[:10],
            "all_channel_triple_summaries": subset,
        }

    result = {
        "schema_version": "refit-full-trace-three-channel-coactivity-0.1",
        "status": "observational_power_coactivity_only",
        "house_id": "REFIT-House3",
        "source_file": source.name,
        "source_bytes": source.stat().st_size,
        "source_sha256_from_prior_full_trace_audit": source_sha256,
        "source_md5_from_publisher_checksum_verification": source_md5,
        "channels": channels,
        "channel_mapping": "unverified; only raw Appliance channel labels are retained",
        "combinations_screened": len(all_combos),
        "thresholds_w": thresholds,
        "selection": {
            "publisher_quality_flag": f"{quality_column}=1 or invalid rows excluded and break bouts",
            "all_three_channels_must_be_at_or_above_threshold_on_same_row": True,
            "max_gap_seconds_within_bout": max_gap_seconds,
            "duration_estimate": f"last Unix - first Unix + {expected_interval_seconds} seconds",
            "all_date_ranges_included": True,
        },
        "trace_counts": {
            "rows": row_count,
            "clear_rows": clear_rows,
            "issues_1_rows": flagged_rows,
            "invalid_quality_rows": invalid_flag_rows,
            "timestamp_gaps_over_limit": gap_count,
        },
        "by_threshold": by_threshold,
        "episodes_csv": str(output_csv),
        "episodes_csv_min_duration_seconds": min_export_duration_seconds,
        "episodes_csv_exported_bout_count": len(exported_bouts),
        "interpretation_limits": [
            "The scan enumerates all 84 three-channel combinations; it does not assume a device mapping.",
            "A bout is same-row thresholded power co-activity in the publisher-cleaned trace, not a device cycle or user task.",
            "REFIT House 3 aggregate readings have reported solar interference; no aggregate or circuit-capacity inference is made.",
            "The trace does not provide task requests, deadlines, remote-control capability, circuit capacity, or agent actions.",
            "Publisher cleaning can include imputed values, and appliance channels are not synchronized; edge times are approximate.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--sha256", default=None)
    parser.add_argument("--md5", default=None)
    parser.add_argument("--max-gap-seconds", type=int, default=16)
    parser.add_argument("--min-export-duration-seconds", type=int, default=60)
    args = parser.parse_args()
    result = scan_trace(
        args.source,
        args.output_csv,
        args.output_json,
        source_sha256=args.sha256,
        source_md5=args.md5,
        max_gap_seconds=args.max_gap_seconds,
        min_export_duration_seconds=args.min_export_duration_seconds,
    )
    print(
        json.dumps(
            {
                "trace_counts": result["trace_counts"],
                "by_threshold": {
                    key: {
                        name: values[name]
                        for name in (
                            "unique_source_rows_with_any_qualifying_triple",
                            "triples_with_any_qualifying_rows",
                            "bout_count_across_triples",
                            "bouts_at_least_60_seconds",
                            "bouts_at_least_300_seconds",
                            "bouts_at_least_1800_seconds",
                            "bouts_at_least_300_seconds_with_both_clear_threshold_boundaries",
                            "duration_seconds_min_median_p90_max",
                        )
                    }
                    for key, values in result["by_threshold"].items()
                },
                "episodes_csv_exported_bout_count": result["episodes_csv_exported_bout_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
