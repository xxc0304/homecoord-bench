"""Inspect an observational appliance-power CSV without making task claims.

The input can be a GREEND daily CSV or another public trace after the caller
explicitly maps its timestamp and device columns. This is a first-stage source
audit: it does not detect cycles, infer user requests, or create episodes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def inspect_csv(
    source: Path,
    *,
    timestamp_column: str,
    device_columns: dict[str, str],
    expected_interval_seconds: float,
    source_url: str,
    house_id: str,
    quality_flag_column: str | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        raise ValueError(f"source file does not exist: {source}")
    if not device_columns:
        raise ValueError("at least one device column is required")
    if expected_interval_seconds <= 0:
        raise ValueError("expected interval must be positive")
    if not source_url or not house_id:
        raise ValueError("source URL and house ID are required")

    digest = hashlib.sha256()
    with source.open("rb") as raw:
        for block in iter(lambda: raw.read(1024 * 1024), b""):
            digest.update(block)

    devices: dict[str, dict[str, Any]] = {
        name: {
            "column": column,
            "valid_rows": 0,
            "missing_or_nonfinite_rows": 0,
            "negative_rows": 0,
            "observed_min_w": None,
            "observed_max_w": None,
        }
        for name, column in device_columns.items()
    }
    total = 0
    first: float | None = None
    last: float | None = None
    previous: float | None = None
    gap_count = 0
    largest_gap = 0.0
    quality_flag_counts = {"clear_rows": 0, "flagged_rows": 0, "invalid_or_missing_rows": 0}

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {timestamp_column, *device_columns.values()}
        if quality_flag_column is not None:
            required.add(quality_flag_column)
        missing = sorted(required - fields)
        if missing:
            raise ValueError(f"missing columns: {missing}")
        if "Issues" in fields and quality_flag_column != "Issues":
            raise ValueError("CSV contains Issues; pass quality_flag_column='Issues' to audit it")
        for line_number, row in enumerate(reader, start=2):
            try:
                stamp = float(row[timestamp_column])
            except (TypeError, ValueError):
                raise ValueError(f"invalid Unix timestamp on CSV line {line_number}") from None
            if not math.isfinite(stamp):
                raise ValueError(f"non-finite Unix timestamp on CSV line {line_number}")
            if previous is not None:
                delta = stamp - previous
                if delta <= 0:
                    raise ValueError(f"duplicate or non-monotonic timestamp on CSV line {line_number}")
                if delta > 2 * expected_interval_seconds:
                    gap_count += 1
                    largest_gap = max(largest_gap, delta)
            if first is None:
                first = stamp
            last = previous = stamp
            total += 1
            if quality_flag_column is not None:
                flag = (row[quality_flag_column] or "").strip()
                if flag == "0":
                    quality_flag_counts["clear_rows"] += 1
                elif flag == "1":
                    quality_flag_counts["flagged_rows"] += 1
                else:
                    quality_flag_counts["invalid_or_missing_rows"] += 1
            for name, column in device_columns.items():
                entry = devices[name]
                raw_value = row[column]
                try:
                    watts = float(raw_value) if raw_value is not None else float("nan")
                except ValueError:
                    watts = float("nan")
                if not math.isfinite(watts):
                    entry["missing_or_nonfinite_rows"] += 1
                    continue
                entry["valid_rows"] += 1
                entry["negative_rows"] += int(watts < 0)
                entry["observed_min_w"] = watts if entry["observed_min_w"] is None else min(entry["observed_min_w"], watts)
                entry["observed_max_w"] = watts if entry["observed_max_w"] is None else max(entry["observed_max_w"], watts)

    if total == 0:
        raise ValueError("CSV has no data rows")
    for entry in devices.values():
        entry["valid_fraction"] = entry["valid_rows"] / total
    report = {
        "schema_version": "power-trace-source-audit-0.1",
        "status": "observational_source_inspection_only",
        "source_file": str(source.resolve()),
        "source_sha256": digest.hexdigest(),
        "source_url": source_url,
        "house_id": house_id,
        "timestamp_column": timestamp_column,
        "expected_interval_seconds": expected_interval_seconds,
        "rows": total,
        "first_unix_timestamp": first,
        "last_unix_timestamp": last,
        "timestamp_gap_count_over_2x_cadence": gap_count,
        "largest_timestamp_gap_seconds": largest_gap,
        "devices": devices,
        "not_inferred": [
            "complete appliance cycles",
            "Agent requests or return times",
            "user deadlines or urgency",
            "remote-control capability",
            "counterfactual coordination effects",
        ],
    }
    if quality_flag_column is not None:
        report["quality_flags"] = {
            "column": quality_flag_column,
            **quality_flag_counts,
            "flagged_fraction": quality_flag_counts["flagged_rows"] / total,
            "clear_fraction": quality_flag_counts["clear_rows"] / total,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--timestamp-column", required=True)
    parser.add_argument("--device", action="append", required=True, metavar="NAME=COLUMN")
    parser.add_argument("--expected-interval-seconds", type=float, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--house-id", required=True)
    parser.add_argument("--quality-flag-column")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    mappings: dict[str, str] = {}
    for item in args.device:
        if "=" not in item:
            parser.error(f"--device must be NAME=COLUMN: {item}")
        name, column = item.split("=", 1)
        if not name or not column or name in mappings:
            parser.error(f"invalid or duplicate device mapping: {item}")
        mappings[name] = column
    report = inspect_csv(
        args.source,
        timestamp_column=args.timestamp_column,
        device_columns=mappings,
        expected_interval_seconds=args.expected_interval_seconds,
        source_url=args.source_url,
        house_id=args.house_id,
        quality_flag_column=args.quality_flag_column,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
