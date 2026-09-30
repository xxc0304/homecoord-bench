"""Audit HomeCoord-to-simulator adapter traces without contacting a backend.

The auditor checks trace completeness, virtual-clock monotonicity, proposal to
command lineage, execution-order evidence, and deterministic replay groups. It
cannot establish simulator physics or validate an upstream license.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "simulator-adapter-trace-0.1"
EVENT_TYPES = {
    "reset",
    "state_snapshot",
    "proposal_scheduled",
    "command_submitted",
    "command_result",
    "tick_advanced",
    "run_finished",
}
REPLAY_FIELDS = ("initial_state_digest", "final_state_digest", "snapshot_digests")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"cannot read {path}: {exc}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {line_number}: each JSONL row must be an object")
            continue
        event["_line_number"] = line_number
        events.append(event)
    if not events and not errors:
        errors.append("trace file is empty")
    return events, errors


def _validate_one(path: Path) -> tuple[dict[str, Any], list[str]]:
    events, errors = _read_jsonl(path)
    if not events:
        return {"path": str(path), "run_id": None, "valid": False}, errors

    first = events[0]
    required_metadata = (
        "schema_version", "run_id", "scenario_id", "schedule_id",
        "backend_revision", "random_seed", "tick_ms",
    )
    for field in required_metadata:
        if field not in first:
            errors.append(f"line {first['_line_number']}: missing {field}")
    if first.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {first.get('schema_version')!r}")
    if not _is_int(first.get("tick_ms")) or first.get("tick_ms", 0) <= 0:
        errors.append("tick_ms must be a positive integer")

    run_id = first.get("run_id")
    for field in ("run_id", "scenario_id", "schedule_id", "backend_revision"):
        if not isinstance(first.get(field), str) or not first[field]:
            errors.append(f"{field} must be a non-empty string")
    if not isinstance(first.get("random_seed"), (str, int)) or isinstance(first.get("random_seed"), bool):
        errors.append("random_seed must be a string or integer")
    last_seq: int | None = None
    last_homecoord_tick: int | None = None
    last_backend_tick: int | None = None
    last_advanced_pair: tuple[int, int] | None = None
    initial_digest: str | None = None
    final_digest: str | None = None
    snapshots: dict[int, str] = {}
    proposals: dict[str, dict[str, Any]] = {}
    commands: dict[str, dict[str, Any]] = {}
    results_by_command: dict[str, dict[str, Any]] = {}
    completed_order: list[tuple[int, str]] = []
    command_order_keys: set[tuple[Any, Any, int]] = set()
    expected_order = first.get("expected_proposal_order")

    for event in events:
        line = event["_line_number"]
        for field in required_metadata:
            if event.get(field) != first.get(field):
                errors.append(f"line {line}: {field} changes within a run")
        if event.get("run_id") != run_id:
            errors.append(f"line {line}: run_id changes within a trace file")
        if event.get("expected_proposal_order") != expected_order:
            errors.append(f"line {line}: expected_proposal_order changes within a run")
        seq = event.get("seq")
        if not _is_int(seq):
            errors.append(f"line {line}: seq must be an integer")
        elif last_seq is not None and seq != last_seq + 1:
            errors.append(f"line {line}: seq must increase by exactly one")
        if _is_int(seq):
            last_seq = seq

        event_type = event.get("event_type")
        if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
            errors.append(f"line {line}: unsupported event_type {event_type!r}")
        for clock_field in ("homecoord_tick", "backend_tick"):
            value = event.get(clock_field)
            if not _is_int(value) or value < 0:
                errors.append(f"line {line}: {clock_field} must be a non-negative integer")
        if _is_int(event.get("homecoord_tick")):
            value = event["homecoord_tick"]
            if last_homecoord_tick is not None and value < last_homecoord_tick:
                errors.append(f"line {line}: HomeCoord virtual clock moved backwards")
            last_homecoord_tick = value
        if _is_int(event.get("backend_tick")):
            value = event["backend_tick"]
            if last_backend_tick is not None and value < last_backend_tick:
                errors.append(f"line {line}: backend virtual clock moved backwards")
            last_backend_tick = value
        if (_is_int(event.get("homecoord_tick")) and _is_int(event.get("backend_tick"))
                and abs(event["homecoord_tick"] - event["backend_tick"]) > 1):
            errors.append(f"line {line}: HomeCoord/backend clocks differ by more than one tick")

        if event_type == "tick_advanced":
            pair = (event["homecoord_tick"], event["backend_tick"])
            if last_advanced_pair is not None and pair != (
                last_advanced_pair[0] + 1, last_advanced_pair[1] + 1
            ):
                errors.append(f"line {line}: tick_advanced must advance both clocks by exactly one tick")
            last_advanced_pair = pair

        if isinstance(event_type, str) and event_type in {"reset", "state_snapshot"}:
            digest = event.get("state_digest")
            backend_tick = event.get("backend_tick")
            if not isinstance(digest, str) or not digest:
                errors.append(f"line {line}: {event_type} requires state_digest")
            elif _is_int(backend_tick):
                old = snapshots.get(backend_tick)
                if old is not None and old != digest:
                    errors.append(f"line {line}: conflicting state digests at backend_tick {backend_tick}")
                snapshots[backend_tick] = digest
            if event_type == "reset":
                if initial_digest is not None:
                    errors.append(f"line {line}: duplicate reset event")
                initial_digest = digest if isinstance(digest, str) else None
            if event_type == "state_snapshot" and event.get("is_final") is True:
                final_digest = digest if isinstance(digest, str) else None

        elif event_type == "proposal_scheduled":
            proposal_id = event.get("proposal_id")
            if not isinstance(proposal_id, str) or not proposal_id:
                errors.append(f"line {line}: proposal_scheduled requires proposal_id")
            elif proposal_id in proposals:
                errors.append(f"line {line}: duplicate proposal_id {proposal_id!r}")
            else:
                proposals[proposal_id] = event

        elif event_type == "command_submitted":
            command_id = event.get("command_id")
            proposal_id = event.get("proposal_id")
            if not isinstance(command_id, str) or not command_id:
                errors.append(f"line {line}: command_submitted requires command_id")
            elif command_id in commands:
                errors.append(f"line {line}: duplicate command_id {command_id!r}")
            else:
                commands[command_id] = event
            if not isinstance(proposal_id, str) or proposal_id not in proposals:
                errors.append(f"line {line}: command references unknown proposal_id {proposal_id!r}")
            if not _is_int(event.get("command_order")) or event.get("command_order", -1) < 0:
                errors.append(f"line {line}: command_order must be a non-negative integer")
            else:
                bundle_id = event.get("command_bundle_id")
                if not isinstance(bundle_id, str) or not bundle_id:
                    errors.append(f"line {line}: command_submitted requires command_bundle_id")
                elif isinstance(proposal_id, str):
                    order_key = (proposal_id, bundle_id, event["command_order"])
                    if order_key in command_order_keys:
                        errors.append(f"line {line}: duplicate command_order within proposal bundle")
                    command_order_keys.add(order_key)

        elif event_type == "command_result":
            command_id = event.get("command_id")
            if not isinstance(command_id, str) or command_id not in commands:
                errors.append(f"line {line}: result references unknown command_id {command_id!r}")
                continue
            if command_id in results_by_command:
                errors.append(f"line {line}: duplicate result for command_id {command_id!r}")
            results_by_command[command_id] = event
            submitted = commands[command_id]
            if event.get("proposal_id") != submitted.get("proposal_id"):
                errors.append(f"line {line}: proposal_id differs from command submission")
            status = event.get("status")
            if not isinstance(status, str) or status not in {"completed", "failed", "rejected"}:
                errors.append(f"line {line}: command_result has invalid status {status!r}")
            if status == "completed":
                execution_order = event.get("execution_order")
                evidence = event.get("order_evidence")
                if not _is_int(execution_order) or execution_order < 0:
                    errors.append(f"line {line}: completed command requires execution_order")
                elif not isinstance(evidence, str) or evidence not in {"backend_ack", "state_observation"}:
                    errors.append(f"line {line}: execution_order requires backend_ack or state_observation evidence")
                else:
                    completed_order.append((execution_order, event["proposal_id"]))

        elif event_type == "run_finished":
            digest = event.get("state_digest")
            if not isinstance(digest, str) or not digest:
                errors.append(f"line {line}: run_finished requires state_digest")
            elif final_digest is not None and digest != final_digest:
                errors.append(f"line {line}: final snapshot differs from run_finished digest")
            else:
                final_digest = digest

    if not any(item.get("event_type") == "reset" for item in events):
        errors.append("trace has no reset event")
    if initial_digest is None:
        errors.append("trace reset has no usable initial state digest")
    if final_digest is None:
        errors.append("trace has no final state snapshot/digest")
    finished_positions = [index for index, item in enumerate(events) if item.get("event_type") == "run_finished"]
    if not finished_positions:
        errors.append("trace has no run_finished event")
    elif len(finished_positions) > 1:
        errors.append("trace has multiple run_finished events")
    elif finished_positions[0] != len(events) - 1:
        errors.append("run_finished must be the final event")
    for proposal_id in proposals:
        if not any(command.get("proposal_id") == proposal_id for command in commands.values()):
            errors.append(f"proposal {proposal_id!r} has no submitted command")
    for command_id in commands:
        if command_id not in results_by_command:
            errors.append(f"command {command_id!r} has no result")

    execution_orders = [order for order, _ in completed_order]
    if len(execution_orders) != len(set(execution_orders)):
        errors.append("completed commands have duplicate execution_order values")
    actual_order: list[str] = []
    for _, proposal_id in sorted(completed_order):
        if not actual_order or proposal_id != actual_order[-1]:
            actual_order.append(proposal_id)
    if expected_order is not None:
        if not isinstance(expected_order, list) or any(not isinstance(item, str) for item in expected_order):
            errors.append("expected_proposal_order must be a list of proposal IDs")
        elif actual_order != expected_order:
            errors.append(f"observed proposal execution order {actual_order} does not match expected {expected_order}")

    record = {
        "path": str(path),
        "run_id": run_id,
        "scenario_id": first.get("scenario_id"),
        "schedule_id": first.get("schedule_id"),
        "backend_revision": first.get("backend_revision"),
        "random_seed": first.get("random_seed"),
        "initial_state_digest": initial_digest,
        "final_state_digest": final_digest,
        "snapshot_digests": sorted((tick, digest) for tick, digest in snapshots.items()),
        "proposal_count": len(proposals),
        "command_count": len(commands),
        "observed_proposal_execution_order": actual_order,
        "valid": not errors,
    }
    return record, errors


def audit_paths(paths: list[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for path in paths:
        record, run_errors = _validate_one(path)
        if isinstance(record.get("run_id"), str) and record.get("run_id") in seen_run_ids:
            run_errors.append(f"duplicate run_id {record['run_id']!r} across input files")
            record["valid"] = False
        if isinstance(record.get("run_id"), str):
            seen_run_ids.add(record["run_id"])
        records.append(record)
        errors.extend({"path": str(path), "error": item} for item in run_errors)

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            json.dumps(record.get("scenario_id"), sort_keys=True),
            json.dumps(record.get("schedule_id"), sort_keys=True),
            json.dumps(record.get("backend_revision"), sort_keys=True),
            json.dumps(record.get("random_seed"), sort_keys=True),
        )
        groups[key].append(record)
    replay_groups = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        signatures = {
            tuple((field, json.dumps(record.get(field), sort_keys=True)) for field in REPLAY_FIELDS)
            for record in group
        }
        consistent = len(signatures) == 1
        replay_groups.append({
            "scenario_id": group[0].get("scenario_id"),
            "schedule_id": group[0].get("schedule_id"),
            "backend_revision": group[0].get("backend_revision"),
            "random_seed": group[0].get("random_seed"),
            "repetition_count": len(group), "deterministic_replay": consistent,
        })
        if not consistent:
            errors.append({
                "path": None,
                "error": (
                    "replay mismatch for scenario/schedule/backend/seed "
                    f"{(group[0].get('scenario_id'), group[0].get('schedule_id'), group[0].get('backend_revision'), group[0].get('random_seed'))!r}"
                ),
            })
    return {
        "schema_version": "simulator-adapter-trace-audit-0.1",
        "input_count": len(paths),
        "valid_count": sum(bool(record["valid"]) for record in records),
        "invalid_count": sum(not record["valid"] for record in records),
        "replay_group_count": len(replay_groups),
        "deterministic_replay_group_count": sum(item["deterministic_replay"] for item in replay_groups),
        "records": records,
        "replay_groups": replay_groups,
        "errors": errors,
        "interpretation": (
            "Trace-contract audit only. Passing does not validate simulator physics, "
            "HomeCoord task labels, or license compatibility."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path, help="one JSONL file per run")
    parser.add_argument("--output", type=Path, help="optional audit JSON output path")
    args = parser.parse_args()
    report = audit_paths(args.traces)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    raise SystemExit(1 if report["invalid_count"] or report["errors"] else 0)


if __name__ == "__main__":
    main()
