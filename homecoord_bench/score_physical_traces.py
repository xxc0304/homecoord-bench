"""Validate and score a set of HC-M06-style sensor trajectories.

Usage: python homecoord_bench/score_physical_traces.py INPUT.json --output AUDIT.json
The input is {"traces": [...]} under the physical-trace v0.1 contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from runtime.physical_trace import score_trace, validate_matched_pair, validate_trace


def audit_bundle(bundle: dict) -> dict:
    if not isinstance(bundle, dict):
        raise ValueError("input must be a JSON object")
    traces = bundle.get("traces")
    if not isinstance(traces, list) or not traces:
        raise ValueError("input must have a nonempty traces list")
    seen_ids = set()
    groups: dict[tuple[str, str, str], dict[str, dict]] = {}
    scores = []
    for trace in traces:
        errors = validate_trace(trace)
        if errors:
            label = trace.get("trace_id", "<missing trace_id>") if isinstance(trace, dict) else "<invalid trace>"
            raise ValueError(f"{label}: " + "; ".join(errors))
        trace_id = trace["trace_id"]
        if trace_id in seen_ids:
            raise ValueError(f"duplicate trace_id: {trace_id}")
        seen_ids.add(trace_id)
        trial = trace["trial"]
        key = (trial["pair_id"], trial["world_config_id"], trial["policy"])
        group = groups.setdefault(key, {})
        condition = trial["condition"]
        if condition in group:
            raise ValueError(f"duplicate {condition} arm for {key}")
        group[condition] = trace
        scores.append(score_trace(trace))
    by_trace_id = {row["trace_id"]: row for row in scores}
    pairs = []
    for key, group in sorted(groups.items()):
        if set(group) != {"conflict", "control"}:
            raise ValueError(f"missing matched conflict/control arm for {key}")
        conflict, control = group["conflict"], group["control"]
        errors = validate_matched_pair(conflict, control)
        if errors:
            raise ValueError(f"invalid pair {key}: " + "; ".join(errors))
        a = by_trace_id[conflict["trace_id"]]
        b = by_trace_id[control["trace_id"]]
        pairs.append({
            "pair_id": key[0], "world_config_id": key[1], "policy": key[2],
            "source_kind": a["source_kind"],
            "conflict_trace_id": a["trace_id"], "control_trace_id": b["trace_id"],
            "conflict_deadline_met": a["sampled_deadline_met"],
            "control_deadline_met": b["sampled_deadline_met"],
            "conflict_minus_control_completion_ms": (
                a["observed_goal_completion_ms"] - b["observed_goal_completion_ms"]
                if a["observed_goal_completion_ms"] is not None and b["observed_goal_completion_ms"] is not None else None),
            "conflict_minus_control_heater_energy_wh": round(a["heater_energy_wh"] - b["heater_energy_wh"], 4),
            "conflict_minus_control_heater_energy_by_deadline_wh": (
                round(a["heater_energy_by_deadline_wh"] - b["heater_energy_by_deadline_wh"], 4)
                if a["heater_energy_by_deadline_wh"] is not None and b["heater_energy_by_deadline_wh"] is not None else None),
            "time_resolution_warning": a["time_resolution_warning"] or b["time_resolution_warning"],
        })
    source_counts: dict[str, int] = {}
    for row in scores:
        source_counts[row["source_kind"]] = source_counts.get(row["source_kind"], 0) + 1
    return {
        "schema_version": "homecoord-physical-trace-audit-0.1",
        "status": "descriptive_trace_audit_only",
        "traces_valid": len(scores), "matched_pairs_valid": len(pairs),
        "source_counts": source_counts,
        "time_resolution_warnings": sum(row["time_resolution_warning"] for row in scores),
        "publication_note": "Valid syntax and matched metadata do not prove physical calibration, independent review, realistic sampling, or a coordination-algorithm gap.",
        "scores": scores, "pairs": pairs,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    input_bytes = args.input.read_bytes()
    bundle = json.loads(input_bytes.decode("utf-8"))
    audit = audit_bundle(bundle)
    audit["input_sha256"] = hashlib.sha256(input_bytes).hexdigest()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: audit[key] for key in ("traces_valid", "matched_pairs_valid",
                                                  "source_counts", "time_resolution_warnings")},
                     ensure_ascii=False, indent=2))
