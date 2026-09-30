"""Extract a small, provenance-preserving event trace from one Figshare CSV.

The source CSV is deliberately kept outside the repository. This script only
exports a compact derived JSON with selected sensor columns and source metadata.
It does not infer Agent actions or causal effects from observational data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any


DATASET_DOI = "10.6084/m9.figshare.27155988"
PAPER_DOI = "10.1038/s41597-025-05166-7"
FILE_ID = "49643052"
WINDOW_MINUTES = 15
ACTIVE_POWER_CUTOFF_KW = 0.1
CONTEXT_FIELDS = (
    "Indoor_CO2_PPM",
    "Indoor_Temperature_C",
    "Indoor_RH_Percent",
    "Outdoor_Temp_C",
    "Liv_Rm_amp_Kitchen_Heat_KW",
    "HVAC_Energy_usage_KW",
)


def number(value: str | None) -> float | None:
    if value is None or value.strip().upper() in {"", "NA", "N/A", "NAN", "NULL"}:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        pass
    for fmt in (
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%y %H:%M:%S",
    ):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            pass
    return None


def compact(row: dict[str, str], state_columns: list[str], heater_column: str | None) -> dict[str, Any]:
    stamp = timestamp(row.get("Timestamp", ""))
    result: dict[str, Any] = {
        "timestamp": stamp.isoformat(timespec="minutes") if stamp else row.get("Timestamp"),
        "co2_ppm": number(row.get("Indoor_CO2_PPM")),
        "indoor_temp_c": number(row.get("Indoor_Temperature_C")),
        "rh_percent": number(row.get("Indoor_RH_Percent")),
        "outdoor_temp_c": number(row.get("Outdoor_Temp_C")),
        "living_room_baseboard_power_kw": number(row.get(heater_column)) if heater_column else None,
        "window_door_states": {},
    }
    for name in state_columns:
        value = number(row.get(name))
        result["window_door_states"][name] = int(value) if value is not None else None
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def summarize_context(event: dict[str, Any]) -> dict[str, Any]:
    before = event["before"]
    after = event["after"]
    co2_before = [r["co2_ppm"] for r in before[-5:] if r["co2_ppm"] is not None]
    co2_after = [r["co2_ppm"] for r in after[:5] if r["co2_ppm"] is not None]
    temp_before = [r["indoor_temp_c"] for r in before[-5:] if r["indoor_temp_c"] is not None]
    temp_after = [r["indoor_temp_c"] for r in after[:5] if r["indoor_temp_c"] is not None]
    heat_before = [r["living_room_baseboard_power_kw"] for r in before[-5:]
                   if r["living_room_baseboard_power_kw"] is not None]
    heat_after = [r["living_room_baseboard_power_kw"] for r in after[:5]
                  if r["living_room_baseboard_power_kw"] is not None]
    event_row = after[0]
    combined = before[-WINDOW_MINUTES:] + after
    other_state_transitions = 0
    for name in event_row["window_door_states"]:
        if name == event["field"]:
            continue
        observed = [row["window_door_states"].get(name) for row in combined]
        other_state_transitions += sum(
            1 for left, right in zip(observed, observed[1:])
            if left is not None and right is not None and left != right
        )

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    return {
        "event_timestamp_minute_bin": event["timestamp"],
        "state_field": event["field"],
        "state_transition": {"from": event["from"], "to": event["to"]},
        "pre_event_5min_mean_co2_ppm": mean(co2_before),
        "post_event_5min_mean_co2_ppm": mean(co2_after),
        "pre_event_5min_mean_indoor_temp_c": mean(temp_before),
        "post_event_5min_mean_indoor_temp_c": mean(temp_after),
        "pre_event_5min_mean_baseboard_power_kw": mean(heat_before),
        "post_event_5min_mean_baseboard_power_kw": mean(heat_after),
        "pre_event_5min_active_heater_samples_over_0_1kw": sum(
            value > ACTIVE_POWER_CUTOFF_KW for value in heat_before
        ),
        "baseboard_power_kw_at_event_minute": event_row["living_room_baseboard_power_kw"],
        "outdoor_temp_c_at_event_minute": event_row["outdoor_temp_c"],
        "state_at_event_minute": event_row["window_door_states"],
        "other_window_door_transitions_in_30min_context": other_state_transitions,
        "target_window_closed_for_all_15_pre_event_minutes": all(
            row["window_door_states"].get(event["field"]) == 0 for row in before[-WINDOW_MINUTES:]
        ),
        "context_rows_before": len(before),
        "context_rows_after_including_event_minute": len(after),
    }


def extract(
    source_csv: Path,
    output_json: Path,
    file_id: str = FILE_ID,
) -> dict[str, Any]:
    digest = sha256_file(source_csv)
    row_count = 0
    first_stamp: datetime | None = None
    last_stamp: datetime | None = None
    intervals: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    joint_state_minutes: Counter[str] = Counter()
    previous_states: dict[str, int | None] = {}
    history: deque[dict[str, Any]] = deque(maxlen=WINDOW_MINUTES)
    pending: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    previous_stamp: datetime | None = None
    state_columns: list[str] = []
    heater_column: str | None = None
    headers: list[str] = []

    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        state_columns = [name for name in headers if name.startswith(("Window_", "Door_"))]
        heater_column = next((name for name in (
            "Liv_Rm_amp_Kitchen_Heat_KW", "Bedroom_1_and_2_Heat_KW",
        ) if name in headers), None)
        if not state_columns or "Indoor_CO2_PPM" not in headers:
            raise ValueError("CSV lacks expected door/window and Indoor_CO2_PPM columns")

        for row in reader:
            row_count += 1
            stamp = timestamp(row.get("Timestamp", ""))
            if stamp is None:
                missing["unparsed_timestamp"] += 1
                continue
            first_stamp = first_stamp or stamp
            last_stamp = stamp
            if previous_stamp is not None:
                delta = int((stamp - previous_stamp).total_seconds())
                intervals[str(delta)] += 1
            previous_stamp = stamp

            for field in CONTEXT_FIELDS:
                if field in headers and number(row.get(field)) is None:
                    missing[field] += 1
            for field in state_columns:
                if number(row.get(field)) is None:
                    missing[field] += 1
            clean = compact(row, state_columns, heater_column)
            open_windows = [
                value for name, value in clean["window_door_states"].items()
                if name.startswith("Window_") and value is not None
            ]
            if any(open_windows):
                joint_state_minutes["any_window_open"] += 1
                if clean["living_room_baseboard_power_kw"] is not None:
                    if clean["living_room_baseboard_power_kw"] > ACTIVE_POWER_CUTOFF_KW:
                        joint_state_minutes["window_open_and_baseboard_power_over_0_1kw"] += 1
                        if clean["co2_ppm"] is not None and clean["indoor_temp_c"] is not None:
                            joint_state_minutes["open_window_heat_co2_temp_all_observed"] += 1

            # Existing transitions receive this row as their next observation.
            for event in pending:
                if len(event["after"]) < WINDOW_MINUTES:
                    event["after"].append(clean)
            finished = [event for event in pending if len(event["after"]) >= WINDOW_MINUTES]
            for event in finished:
                before = event["before"]
                after = event["after"]
                co2_values = [r["co2_ppm"] for r in before[-5:] + after[:5] if r["co2_ppm"] is not None]
                if len(before) >= 10 and len(after) >= WINDOW_MINUTES and len(co2_values) >= 8:
                    event["summary"] = summarize_context(event)
                    events.append(event)
            if finished:
                finished_ids = {id(event) for event in finished}
                pending = [event for event in pending if id(event) not in finished_ids]

            for field in state_columns:
                value_f = number(row.get(field))
                value = int(value_f) if value_f is not None else None
                prev = previous_states.get(field)
                if prev is not None and value is not None and value != prev:
                    transitions[field] += 1
                    # Keep full contexts only for fenestration changes. Door events
                    # remain in transition counts but are not treated as ventilation events.
                    if field.startswith("Window_") and len(history) >= 10:
                        pending.append({
                            "field": field,
                            "timestamp": clean["timestamp"],
                            "from": prev,
                            "to": value,
                            "before": list(history),
                            "after": [clean],
                        })
                # Do not infer a transition across missing sensor bins.
                previous_states[field] = value
            history.append(clean)

    # Choose up to three well-observed transitions with the largest 5-minute CO2
    # change. This is a reproducible convenience selection, not a causal estimate.
    # Prefer the measured state pattern most relevant to the project's C2
    # question: a window opens while the baseboard heater is already drawing
    # power, the outdoor air is colder, and the main entry door is closed.
    # This selects context; it does not claim that heating should be turned off.
    relevant = [
        event for event in events
        if event["from"] == 0
        and event["to"] == 1
        and event["summary"]["pre_event_5min_active_heater_samples_over_0_1kw"] >= 4
        and (event["summary"]["baseboard_power_kw_at_event_minute"] or 0) > ACTIVE_POWER_CUTOFF_KW
        and event["summary"]["outdoor_temp_c_at_event_minute"] is not None
        and event["summary"]["pre_event_5min_mean_indoor_temp_c"] is not None
        and event["summary"]["outdoor_temp_c_at_event_minute"]
            < event["summary"]["pre_event_5min_mean_indoor_temp_c"]
        and event["summary"]["state_at_event_minute"].get("Door_1_1") == 0
        and event["summary"]["other_window_door_transitions_in_30min_context"] == 0
        and event["summary"]["target_window_closed_for_all_15_pre_event_minutes"]
    ]
    candidates = relevant or events
    ranked = sorted(
        candidates,
        key=lambda e: (
            (e["summary"]["pre_event_5min_mean_co2_ppm"] or 0),
            abs((e["summary"]["post_event_5min_mean_co2_ppm"] or 0)
                - (e["summary"]["pre_event_5min_mean_co2_ppm"] or 0)),
        ),
        reverse=True,
    )[:3]
    selected_windows = []
    for event in ranked:
        sample_rows = event["before"][-WINDOW_MINUTES:] + event["after"]
        origin = timestamp(event["timestamp"])
        samples = []
        for item in sample_rows:
            stamp = timestamp(item["timestamp"])
            minutes = int((stamp - origin).total_seconds() // 60) if stamp and origin else None
            samples.append({"minutes_from_transition": minutes, **item})
        selected_windows.append({
            "event": event["summary"],
            "samples": samples,
            "interpretation": (
                "Observed door/window-state and sensor co-trajectory only. "
                "The state change was not randomized, no Agent command was recorded, "
                "and this association is not a causal action effect."
            ),
        })

    result = {
        "schema_version": "homecoord-public-real-trace-pilot-0.1",
        "purpose": "A small measured-state trace for provenance and simulator-context calibration; not a benchmark episode or Agent trajectory.",
        "source": {
            "paper_title": "Dataset on occupant behavior, indoor environment, and energy use before and after dormitory retrofit",
            "paper_citation": "Pandey, P.R., Liu, Y., Wilson, N. et al. Scientific Data 12, 798 (2025).",
            "paper_doi": PAPER_DOI,
            "dataset_title": "A Two-Year Comprehensive Dataset on Occupant Behavior, Indoor Environmental Quality, and Energy Use Before and After Dormitory Retrofits",
            "dataset_attribution": "Pratik Pandey, Nina Wilson, and Bing Dong; Figshare dataset posted 2024-10-07",
            "dataset_doi": DATASET_DOI,
            "figshare_url": "https://figshare.com/articles/dataset/A_Two-Year_Comprehensive_Dataset_on_Occupant_Behavior_Indoor_Environmental_Quality_and_Energy_Use_Before_and_After_Dormitory_Retrofits/27155988",
            "download_url": f"https://figshare.com/ndownloader/files/{file_id}",
            "file_id": file_id,
            "file_name": source_csv.name,
            "local_scan_file_name": source_csv.name,
            "folder": "Before_Retro_Path_Folder",
            "unit_scope": "one anonymized pre-retrofit dorm unit; the paper says each dorm has a separate file",
            "license": "CC BY 4.0; attribution required",
            "retrieved_on": "2026-09-28",
            "raw_file_size_bytes": source_csv.stat().st_size,
            "raw_file_sha256": digest,
        },
        "measurement_semantics": {
            "standardized_csv_resolution": "one minute",
            "fenestration": "underlying contact sensors log state changes at second resolution; standardized CSV marks a minute open if it was open at any time during that minute",
            "indoor_environment": "originally five-minute sensor samples, linearly interpolated to one minute",
            "power": "originally recorded at one-minute intervals",
        },
        "representative_event_selection_rule": {
            "state_change": "Window_1_1 transitions from 0 to 1 after all 15 preceding minute bins were closed",
            "heating_context": "baseboard power exceeds 0.1 kW in at least 4 of the previous 5 observed bins and in the event bin; this threshold only excludes near-zero meter noise",
            "weather_context": "outdoor temperature is below the preceding 5-minute mean indoor temperature",
            "aperture_context": "Door_1_1 is closed and no other observed window/door state changes in the 30-minute trace; missing Door_2_2 readings remain an explicit limitation",
            "tie_break": "among qualifying events, sort by highest pre-event 5-minute mean CO2, then absolute pre/post 5-minute mean CO2 difference",
        },
        "scan_summary": {
            "rows_with_parseable_timestamp": row_count - missing["unparsed_timestamp"],
            "first_timestamp": first_stamp.isoformat(timespec="minutes") if first_stamp else None,
            "last_timestamp": last_stamp.isoformat(timespec="minutes") if last_stamp else None,
            "interval_seconds_counts": dict(intervals),
            "state_transition_counts": dict(transitions),
            "joint_state_minute_counts": dict(joint_state_minutes),
            "missing_value_counts_for_available_context_columns": dict(missing),
            "missing_value_percentages_over_csv_rows": {
                field: round(count * 100 / row_count, 3) if row_count else None
                for field, count in missing.items()
            },
            "state_columns": state_columns,
            "baseboard_power_column": heater_column,
            "window_events_with_15min_context_and_CO2": len(events),
            "relevant_window_open_with_heating_candidates": len(relevant),
        },
        "selected_event_windows": selected_windows,
        "limitations": [
            "Observational dormitory measurements are not real household-agent tasks or command/acknowledgement logs.",
            "A single anonymized unit is not an independent household sample or a population distribution.",
            "The standardized minute data cannot validate sub-minute or one-second control latency.",
            "Indoor environmental values were interpolated from five-minute measurements, so neighboring minute rows are not independent sensor readings.",
            "Co-occurrence of a window-state change and CO2/temperature change does not establish that the window action caused the change; occupancy, door operation, weather, HVAC/heating, and other factors may contribute.",
            "Use this trace as measured context or calibration evidence. Counterfactual policy outcomes require a validated simulator or physical experiment.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True, help="Path to the downloaded source CSV")
    parser.add_argument("--output", type=Path, required=True, help="Path for compact derived JSON")
    parser.add_argument(
        "--file-id",
        default=FILE_ID,
        help="Figshare file ID recorded in the provenance block",
    )
    args = parser.parse_args()
    result = extract(args.csv, args.output, file_id=args.file_id)
    print(json.dumps(result["scan_summary"], ensure_ascii=False, indent=2))
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
