"""Extract observed REFIT co-activity windows, not task conflicts.

This is a descriptive audit of the publisher-cleaned trace. Rows marked by the
publisher's Issues flag are excluded and break windows. A pair window continues
only while both channels exceed the selected threshold and adjacent timestamps
remain within the selected gap limit. The output must not be interpreted as
user tasks, appliance service cycles, or coordination outcomes.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


DEVICES = {
    "dryer": "Appliance2",
    "washer": "Appliance3",
    "dishwasher": "Appliance4",
}


def _close_window(state: dict[str, Any] | None, pair: tuple[str, str], output: list[dict[str, Any]]) -> None:
    if state is None:
        return
    duration = max(8, state["last_unix"] - state["start_unix"] + 8)
    output.append(
        {
            "pair": list(pair),
            "start_time": state["start_time"],
            "end_time": state["last_time"],
            "start_unix": state["start_unix"],
            "end_unix": state["last_unix"],
            "source_csv_line_start": state["line_start"],
            "source_csv_line_end": state["line_end"],
            "qualifying_rows": state["rows"],
            "duration_estimate_seconds": duration,
            "mean_power_w_by_device": {
                device: round(total / state["rows"], 2)
                for device, total in state["power_sum_w"].items()
            },
            "peak_pair_power_w": state["peak_pair_power_w"],
            "peak_all_three_power_w": state["peak_all_three_power_w"],
        }
    )


def extract_windows(
    source: Path,
    *,
    start_date_inclusive: date,
    end_date_exclusive: date,
    threshold_w: float,
    max_gap_seconds: float,
    device_columns: dict[str, str] = DEVICES,
    house_id: str = "H5",
) -> dict[str, Any]:
    if not source.is_file():
        raise ValueError(f"source file does not exist: {source}")
    if threshold_w <= 0 or max_gap_seconds <= 0:
        raise ValueError("threshold and max gap must be positive")

    pairs = list(itertools.combinations(device_columns, 2))
    active_states: dict[tuple[str, str], dict[str, Any] | None] = {pair: None for pair in pairs}
    windows: list[dict[str, Any]] = []
    rows_in_window = clear_rows = flagged_rows = invalid_flag_rows = 0
    qualifying_rows_by_pair: dict[str, int] = defaultdict(int)
    previous_unix: int | None = None

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"Time", "Unix", "Issues", *device_columns.values()}
        missing = sorted(required - fields)
        if missing:
            raise ValueError(f"missing columns: {missing}")

        for line_number, row in enumerate(reader, start=2):
            row_date = date.fromisoformat(row["Time"][:10])
            if row_date < start_date_inclusive or row_date >= end_date_exclusive:
                continue
            rows_in_window += 1
            timestamp = int(float(row["Unix"]))
            flag = (row["Issues"] or "").strip()

            if flag != "0":
                if flag == "1":
                    flagged_rows += 1
                else:
                    invalid_flag_rows += 1
                for pair, state in active_states.items():
                    _close_window(state, pair, windows)
                    active_states[pair] = None
                previous_unix = timestamp
                continue

            clear_rows += 1
            if previous_unix is not None and timestamp - previous_unix > max_gap_seconds:
                for pair, state in active_states.items():
                    _close_window(state, pair, windows)
                    active_states[pair] = None
            previous_unix = timestamp

            watts = {device: float(row[column]) for device, column in device_columns.items()}
            active = {device for device, power in watts.items() if power >= threshold_w}
            qualifying_pairs = {
                pair for pair in pairs if pair[0] in active and pair[1] in active
            }

            for pair in pairs:
                pair_name = "+".join(pair)
                state = active_states[pair]
                if pair not in qualifying_pairs:
                    _close_window(state, pair, windows)
                    active_states[pair] = None
                    continue

                qualifying_rows_by_pair[pair_name] += 1
                pair_power = watts[pair[0]] + watts[pair[1]]
                all_three_power = sum(watts.values())
                if state is None:
                    active_states[pair] = {
                        "start_time": row["Time"],
                        "last_time": row["Time"],
                        "start_unix": timestamp,
                        "last_unix": timestamp,
                        "line_start": line_number,
                        "line_end": line_number,
                        "rows": 1,
                        "power_sum_w": {device: watts[device] for device in pair},
                        "peak_pair_power_w": pair_power,
                        "peak_all_three_power_w": all_three_power,
                    }
                else:
                    state["last_time"] = row["Time"]
                    state["last_unix"] = timestamp
                    state["line_end"] = line_number
                    state["rows"] += 1
                    for device in pair:
                        state["power_sum_w"][device] += watts[device]
                    state["peak_pair_power_w"] = max(state["peak_pair_power_w"], pair_power)
                    state["peak_all_three_power_w"] = max(
                        state["peak_all_three_power_w"], all_three_power
                    )

    for pair, state in active_states.items():
        _close_window(state, pair, windows)

    by_pair: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        pair_name = "+".join(pair)
        rows = [window for window in windows if "+".join(window["pair"]) == pair_name]
        durations = [window["duration_estimate_seconds"] for window in rows]
        by_pair[pair_name] = {
            "qualifying_sample_rows": qualifying_rows_by_pair[pair_name],
            "window_count": len(rows),
            "median_duration_seconds": round(statistics.median(durations), 1) if durations else None,
            "p90_duration_seconds": (
                round(sorted(durations)[int(0.9 * (len(durations) - 1))], 1) if durations else None
            ),
            "windows_at_least_60_seconds": sum(duration >= 60 for duration in durations),
            "windows_at_least_300_seconds": sum(duration >= 300 for duration in durations),
            "windows_at_least_1800_seconds": sum(duration >= 1800 for duration in durations),
        }

    windows.sort(key=lambda item: (item["start_unix"], item["pair"]))
    for index, window in enumerate(windows, start=1):
        window["window_id"] = f"REFIT-{house_id}-COACT-{index:06d}"

    return {
        "schema_version": "refit-observed-coactivity-windows-0.1",
        "status": "descriptive_observation_only_not_task_or_conflict_labels",
        "house_id": f"REFIT-{house_id}",
        "source_file_name": source.name,
        "source_file_size_bytes": source.stat().st_size,
        "selection": {
            "device_columns": device_columns,
            "date_field": "Time",
            "start_date_inclusive": start_date_inclusive.isoformat(),
            "end_date_exclusive": end_date_exclusive.isoformat(),
            "publisher_quality_flag": "Issues=1 rows excluded and break windows",
            "threshold_w": threshold_w,
            "pair_active_when_both_channels_at_or_above_threshold": True,
            "max_gap_seconds_within_window": max_gap_seconds,
            "duration_estimate": "last timestamp - first timestamp + 8 seconds",
        },
        "counts": {
            "rows_in_date_window": rows_in_window,
            "clear_rows": clear_rows,
            "issues_1_rows_excluded": flagged_rows,
            "invalid_or_missing_quality_flags": invalid_flag_rows,
        },
        "by_pair": by_pair,
        "windows": windows,
        "interpretation_limits": [
            "A co-activity window is a same-row measured power overlap under a researcher-selected threshold.",
            "Rows are temporally correlated and sensor channels are not synchronized; this is not a count of independent events.",
            "The data contain no user task requests, deadlines, remote-start capability, circuit capacity, or agent actions.",
            "REFIT cleaning may forward-fill short gaps or zero-fill longer gaps; zeros are not reliable off-state labels.",
            "Do not use these windows as appliance cycles, task service durations, or conflict ground truth without separate review.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start-date", default="2013-09-26")
    parser.add_argument("--end-date-exclusive", default="2014-11-21")
    parser.add_argument("--threshold-w", type=float, default=100)
    parser.add_argument("--max-gap-seconds", type=float, default=16)
    parser.add_argument("--dryer-column", default=DEVICES["dryer"])
    parser.add_argument("--washer-column", default=DEVICES["washer"])
    parser.add_argument("--dishwasher-column", default=DEVICES["dishwasher"])
    parser.add_argument("--house-id", default="H5", help="Short house identifier used in output IDs, e.g. H1 or H5")
    args = parser.parse_args()
    result = extract_windows(
        args.source,
        start_date_inclusive=date.fromisoformat(args.start_date),
        end_date_exclusive=date.fromisoformat(args.end_date_exclusive),
        threshold_w=args.threshold_w,
        max_gap_seconds=args.max_gap_seconds,
        device_columns={
            "dryer": args.dryer_column,
            "washer": args.washer_column,
            "dishwasher": args.dishwasher_column,
        },
        house_id=args.house_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result["counts"], "by_pair": result["by_pair"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
