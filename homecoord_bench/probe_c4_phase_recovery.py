"""Phase-aligned C4 replay and an explicit synthetic stop/restart contract.

Event times are counterfactual offsets from each saved cleaning proposal's
earliest physical start. They isolate lifecycle phases, not event frequencies.
The separate recovery contract models one robot action and is checked against
the core simulator's gate-only behavior before comparing stop policies.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from evaluate import ROOT
from probe_c4_recorded_proposals import POLICIES, SOURCE, make_episode
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


MODEL_SOURCE = ROOT / "results" / "c4_recorded_proposal_boundary_20260928.json"
OUTPUT = ROOT / "results" / "c4_phase_recovery_20260928.json"
COMMAND_DELAY_MS = 100
ROBOT_DURATION_MS = 3000
STOP_DELAY_MS = 200
RESIDENT_STAY_MS = 2000
PHASES = ("no_event", "precommit", "inflight", "postcomplete")


def event_times(clean_latency_ms: int, phase: str) -> tuple[int | None, int | None]:
    start = clean_latency_ms + COMMAND_DELAY_MS
    if phase == "no_event":
        return None, None
    if phase == "precommit":
        entry = start - 100
    elif phase == "inflight":
        entry = start + ROBOT_DURATION_MS // 2
    elif phase == "postcomplete":
        entry = start + ROBOT_DURATION_MS + 1000
    else:
        raise ValueError(phase)
    return entry, entry + RESIDENT_STAY_MS


def phase_episode(phase: str, clean_latency_ms: int) -> dict:
    episode = make_episode("no_event")
    episode["episode_id"] = f"HC-C4-PHASE-{phase.upper()}-{clean_latency_ms}"
    entry, leave = event_times(clean_latency_ms, phase)
    episode["exogenous_events"] = [] if entry is None else [
        {"at_ms": entry, "event": "resident_enters", "patch": {"bedroom.occupied": True}},
        {"at_ms": leave, "event": "resident_leaves", "patch": {"bedroom.occupied": False}},
    ]
    episode["variant"] = {
        "phase": phase, "event_alignment": "relative_to_independent_earliest_action_start",
        "resident_entry_ms": entry, "resident_leave_ms": leave,
    }
    return episode


def recovery_contract(clean_latency_ms: int, phase: str,
                      policy: str, stop_delay_ms: int = STOP_DELAY_MS) -> dict:
    """Deterministic one-action contract; task progress restarts from zero."""
    if policy not in {"GateOnly", "StopOnly", "StopAndRestart"}:
        raise ValueError(policy)
    if stop_delay_ms < 0:
        raise ValueError("stop delay must be nonnegative")
    earliest_start = clean_latency_ms + COMMAND_DELAY_MS
    entry, leave = event_times(clean_latency_ms, phase)
    first_start = earliest_start
    cancelled_at = None
    retry_start = None
    rejection = False
    if entry is not None and entry <= earliest_start < leave:
        rejection = True
        first_start = None
        if policy == "StopAndRestart":
            retry_start = leave + COMMAND_DELAY_MS
            completion = retry_start + ROBOT_DURATION_MS
        else:
            completion = None
        unsafe_ms = 0
    else:
        natural_finish = earliest_start + ROBOT_DURATION_MS
        in_flight_entry = entry is not None and earliest_start < entry < natural_finish
        if in_flight_entry and policy in {"StopOnly", "StopAndRestart"}:
            cancelled_at = min(entry + stop_delay_ms, natural_finish)
            # A stop acknowledged at or after natural completion is too late.
            if cancelled_at >= natural_finish:
                cancelled_at = None
                completion = natural_finish
                unsafe_ms = min(leave, natural_finish) - entry
            else:
                unsafe_ms = min(cancelled_at, leave) - entry
                if policy == "StopAndRestart":
                    retry_start = max(leave, cancelled_at) + COMMAND_DELAY_MS
                    completion = retry_start + ROBOT_DURATION_MS
                else:
                    completion = None
        else:
            completion = natural_finish
            unsafe_ms = (max(0, min(leave, natural_finish) - max(entry, earliest_start))
                         if entry is not None else 0)
    return {
        "phase": phase, "policy": policy, "clean_model_latency_ms": clean_latency_ms,
        "resident_entry_ms": entry, "resident_leave_ms": leave,
        "first_action_start_ms": first_start, "cancelled_at_ms": cancelled_at,
        "retry_start_ms": retry_start, "task_completion_ms": completion,
        "task_served": completion is not None,
        "stale_rejected_before_start": rejection,
        "unsafe_overlap_duration_ms": unsafe_ms,
        "stop_delay_assumption_ms": stop_delay_ms,
        "restart_progress_semantics": "full_cycle_restarts_from_zero",
    }


def run() -> dict:
    source_bytes = MODEL_SOURCE.read_bytes()
    source = json.loads(source_bytes)
    core_rows = []
    recovery_rows = []
    for row in source["rows"]:
        records = row.get("model_records", {})
        if set(records) != {"bedroom_clean", "bedroom_occupancy"}:
            continue
        latency = records["bedroom_clean"]["logical_latency_ms"]
        for phase in PHASES:
            episode = phase_episode(phase, latency)
            ordered = [records[task["task_id"]] for task in episode["task_stream"]]
            for policy in POLICIES:
                client = MemoryReplayClient(deepcopy(ordered))
                trace, result = run_event_simulation(
                    deepcopy(episode), client, policy, "recorded-proposal replay",
                    shared_safety_gate=True,
                )
                client.assert_consumed()
                start = next((event["timestamp_ms"] for event in trace["events"]
                              if event["type"] == "action_started"
                              and event["task_id"] == "bedroom_clean"), None)
                completion = next((event["timestamp_ms"] for event in trace["events"]
                                   if event["type"] == "action_completed"
                                   and event["task_id"] == "bedroom_clean"), None)
                core_rows.append({
                    "repetition": row["repetition"], "phase": phase, "policy": policy,
                    "resident_entry_ms": event_times(latency, phase)[0],
                    "clean_model_latency_ms": latency,
                    "clean_start_ms": start, "clean_completion_ms": completion,
                    "clean_task_served": result["task_service"]["bedroom_clean"],
                    "final_goal_success": result["final_goal_success"],
                    "process_valid_success": result["process_valid_success"],
                    "stale_at_action_start_count": result["stale_at_action_start_count"],
                    "in_flight_precondition_invalidated_action_count": result[
                        "in_flight_precondition_invalidated_action_count"
                    ],
                    "unsafe_overlap_duration_ms": result[
                        "state_constraint_violation_duration_ms"
                    ],
                })
            for policy in ("GateOnly", "StopOnly", "StopAndRestart"):
                recovery_rows.append({
                    "repetition": row["repetition"],
                    **recovery_contract(latency, phase, policy),
                })
    # A meaningful contract check: the isolated gate-only executor must agree
    # with the established event runtime on starts, completion, and unsafe time.
    for core in core_rows:
        if core["policy"] != "IndependentMultiAgent":
            continue
        contract = next(item for item in recovery_rows
                        if item["repetition"] == core["repetition"]
                        and item["phase"] == core["phase"]
                        and item["policy"] == "GateOnly")
        assert core["clean_start_ms"] == contract["first_action_start_ms"]
        assert core["clean_completion_ms"] == contract["task_completion_ms"]
        assert core["unsafe_overlap_duration_ms"] == contract["unsafe_overlap_duration_ms"]
    payload = {
        "status": "synthetic_phase_aligned_counterfactual_and_explicit_stop_restart_contract",
        "model_source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "new_api_calls": 0,
        "design": {
            "phase_alignment": "same saved proposal per condition; resident event fixed relative to its earliest physical start",
            "phase_offsets_ms": {"precommit": -100, "inflight": 1500,
                                 "postcomplete": 4000},
            "resident_stay_ms": RESIDENT_STAY_MS,
            "command_delay_ms": COMMAND_DELAY_MS,
            "robot_duration_ms": ROBOT_DURATION_MS,
            "stop_delay_ms": STOP_DELAY_MS,
            "retry_semantics": "after resident leaves, issue command then restart full cycle from zero",
            "stop_and_restart_is_isolated_contract_not_integrated_event_policy": True,
        },
        "core_rows": core_rows,
        "recovery_rows": recovery_rows,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = run()
    print(json.dumps({"core_rows": len(report["core_rows"]),
                      "recovery_rows": len(report["recovery_rows"]),
                      "output": str(OUTPUT)}, ensure_ascii=False))
