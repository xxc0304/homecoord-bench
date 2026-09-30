"""Synthetic pilot: command acceptance is not physical execution.

Two agents cooperate: VentilationAgent requests window closure and ClimateAgent
may start cooling only after the window is physically closed. The command is
acknowledged at t=0 even when execution is delayed or fails. This small model
deliberately separates acknowledgement, physical state, and status reports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import ROOT


COOLING_RELEASE_MS = 100
COOLING_DEADLINE_MS = 1200
FIXED_WAIT_UNTIL_MS = 500
ACTIVE_QUERY_LATENCY_MS = 150
ACTIVE_QUERY_INTERVAL_MS = 200
POLICIES = ("AckOptimistic", "FixedWait", "PassiveConfirmation", "ActiveStatusQuery")


def simulate(close_at_ms: int | None, status_lag_ms: int, policy: str) -> dict:
    """Return an observable trace plus outcome; None means actuator failure."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    if close_at_ms is not None and close_at_ms < 0:
        raise ValueError("close time must be nonnegative")
    if status_lag_ms < 0:
        raise ValueError("status lag must be nonnegative")

    events = [
        {"at_ms": 0, "type": "close_command_accepted", "agent": "VentilationAgent"},
        {"at_ms": COOLING_RELEASE_MS, "type": "cooling_request", "agent": "ClimateAgent"},
    ]
    if close_at_ms is not None:
        events.extend([
            {"at_ms": close_at_ms, "type": "window_physically_closed", "observer": "simulator_only"},
            {"at_ms": close_at_ms + status_lag_ms, "type": "passive_status_closed", "agent": "ClimateAgent"},
        ])

    start_ms = None
    query_count = 0
    if policy == "AckOptimistic":
        start_ms = COOLING_RELEASE_MS
    elif policy == "FixedWait":
        start_ms = FIXED_WAIT_UNTIL_MS
    elif policy == "PassiveConfirmation":
        if close_at_ms is not None:
            start_ms = max(COOLING_RELEASE_MS, close_at_ms + status_lag_ms)
    else:
        # At each query completion, the device returns its current physical
        # state. A separate agent does not learn that state before this reply.
        reply_at = COOLING_RELEASE_MS + ACTIVE_QUERY_LATENCY_MS
        while reply_at <= COOLING_DEADLINE_MS:
            query_count += 1
            closed = close_at_ms is not None and close_at_ms <= reply_at
            events.append({"at_ms": reply_at, "type": "status_query_reply", "closed": closed,
                           "agent": "ClimateAgent"})
            if closed:
                start_ms = reply_at
                break
            reply_at += ACTIVE_QUERY_INTERVAL_MS

    if start_ms is not None:
        events.append({"at_ms": start_ms, "type": "cooling_started", "agent": "ClimateAgent"})
    physically_valid = start_ms is None or (close_at_ms is not None and start_ms >= close_at_ms)
    on_time_valid = physically_valid and start_ms is not None and start_ms <= COOLING_DEADLINE_MS
    earliest_valid_start = None if close_at_ms is None else max(COOLING_RELEASE_MS, close_at_ms)
    return {
        "close_at_ms": close_at_ms,
        "status_lag_ms": status_lag_ms,
        "policy": policy,
        "cooling_started_ms": start_ms,
        "physically_valid": physically_valid,
        "on_time_valid": on_time_valid,
        "unnecessary_wait_ms": None if start_ms is None or earliest_valid_start is None or not physically_valid
        else start_ms - earliest_valid_start,
        "query_count": query_count,
        "events": sorted(events, key=lambda event: event["at_ms"]),
    }


def run(output_path: Path) -> dict:
    # Each delay is crossed with each observation lag; failure has the same
    # command acceptance and cooling request but no physical close event.
    cases = [(delay, lag) for delay in (0, 200, 600, 1000, 1400)
             for lag in (0, 100, 500)] + [(None, lag) for lag in (0, 100, 500)]
    rows = [simulate(delay, lag, policy) for delay, lag in cases for policy in POLICIES]
    summary = {
        policy: {
            "cases": len(cases),
            "physical_violations": sum(not row["physically_valid"] for row in rows if row["policy"] == policy),
            "valid_on_time": sum(row["on_time_valid"] for row in rows if row["policy"] == policy),
            "unserved": sum(row["cooling_started_ms"] is None for row in rows if row["policy"] == policy),
            "total_queries": sum(row["query_count"] for row in rows if row["policy"] == policy),
        }
        for policy in POLICIES
    }
    payload = {
        "experiment": "command_ack_vs_physical_effect_pilot",
        "status": "synthetic_unreviewed_design_experiment",
        "scenario": "Window close command is accepted at 0 ms; cooling is requested at 100 ms and must start by 1200 ms only after physical closure.",
        "semantics": "A passive status report lags the physical event; an active query returns the current physical state after 150 ms and can repeat every 200 ms.",
        "limitations": "All delays, deadlines, and query capabilities are synthetic. This is a two-agent event model, not a real-device or LLM experiment.",
        "summary": summary,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "execution_uncertainty_pilot_20260924.json")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], ensure_ascii=False, indent=2))
