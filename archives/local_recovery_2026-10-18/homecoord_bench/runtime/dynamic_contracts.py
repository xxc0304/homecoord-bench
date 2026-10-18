"""Synthetic device contracts for capacity-change and mode-choice probes.

Power is kW, work is kW seconds, and the clock uses 100 ms ticks. These are
controlled mechanism assumptions, not calibrated appliance trajectories.
The physical interlock sees true capacity; an energy Agent reports it later.
"""

from __future__ import annotations

from copy import deepcopy

STEP_MS = 100


def validate_contracts(jobs: list[dict], capacity_events: list[dict]) -> None:
    if not jobs or len({j["id"] for j in jobs}) != len(jobs):
        raise ValueError("jobs require unique IDs")
    for job in jobs:
        modes = job["modes_kw"]
        if (not isinstance(modes, dict) or not modes or
                any(not isinstance(p, (int, float)) or isinstance(p, bool) or p <= 0
                    for p in modes.values())):
            raise ValueError(f"{job['id']}: positive power modes required")
        if job["work_kws"] <= 0 or job["deadline_ms"] <= 0:
            raise ValueError(f"{job['id']}: positive work and deadline required")
        if job["stop_ack_ms"] < 0 or job["resume_loss_kws"] < 0:
            raise ValueError(f"{job['id']}: invalid pause contract")
        if job.get("release_ms", 0) < 0 or job.get("release_ms", 0) % STEP_MS:
            raise ValueError(f"{job['id']}: invalid release tick")
    if not capacity_events or capacity_events[0]["at_ms"] != 0:
        raise ValueError("initial capacity at zero required")
    if [e["at_ms"] for e in capacity_events] != sorted({e["at_ms"] for e in capacity_events}):
        raise ValueError("capacity events require distinct ordered times")
    for event in capacity_events:
        if event["capacity_kw"] <= 0 or event["report_delay_ms"] < 0:
            raise ValueError("invalid capacity report")
        if event["at_ms"] % STEP_MS or event["report_delay_ms"] % STEP_MS:
            raise ValueError("capacity events must align to clock ticks")


def simulate(jobs: list[dict], capacity_events: list[dict], *,
             mode_choice: bool, horizon_ms: int = 20_000) -> dict:
    """Replay one deterministic schedule with identical device and safety floor.

    The allocator learns capacity only when the energy Agent's report arrives.
    Hardware sheds load instantly on a real capacity decrease. A shed device
    may resume only after its stop acknowledgement; its restart loses work.
    No step may exceed the real capacity, including during a delayed report.
    """
    validate_contracts(jobs, capacity_events)
    if horizon_ms <= 0 or horizon_ms % STEP_MS:
        raise ValueError("horizon must be a positive whole number of ticks")
    records = {j["id"]: {**deepcopy(j), "remaining_kws": float(j["work_kws"]),
                         "mode": None, "ack_until_ms": 0, "started": False,
                         "finish_ms": None, "failed": False,
                         "trip_count": 0, "pause_count": 0,
                         "blocked_report_version": -1} for j in jobs}
    ordered = sorted(records.values(), key=lambda j: (j["deadline_ms"], j["id"]))
    true_capacity = reported_capacity = float(capacity_events[0]["capacity_kw"])
    pending_reports: list[tuple[int, float]] = []
    report_version = 0
    events = []
    gate_rejections = 0
    peak_power = 0.0
    for now in range(0, horizon_ms, STEP_MS):
        for change in capacity_events:
            if change["at_ms"] != now:
                continue
            true_capacity = float(change["capacity_kw"])
            pending_reports.append((now + change["report_delay_ms"], true_capacity))
            events.append({"at_ms": now, "type": "physical_capacity_change",
                           "capacity_kw": true_capacity})
            # The common hardware interlock sheds in reverse priority order.
            active = [j for j in ordered if j["mode"] is not None]
            active_power = sum(j["modes_kw"][j["mode"]] for j in active)
            for job in reversed(active):
                if active_power <= true_capacity + 1e-9:
                    break
                active_power -= job["modes_kw"][job["mode"]]
                job["mode"] = None
                job["ack_until_ms"] = now + job["stop_ack_ms"]
                job["trip_count"] += 1
                if job.get("interruptible", False):
                    job["remaining_kws"] += job["resume_loss_kws"]
                else:
                    job["failed"] = True  # emergency stop, no claimed safe restart
                events.append({"at_ms": now, "type": "hardware_trip",
                               "job_id": job["id"], "stop_ack_at_ms": job["ack_until_ms"]})
        for report_at, value in list(pending_reports):
            if report_at == now:
                reported_capacity = value
                report_version += 1
                pending_reports.remove((report_at, value))
                events.append({"at_ms": now, "type": "energy_agent_report",
                               "capacity_kw": value})
        active_power = sum(j["modes_kw"][j["mode"]] for j in ordered if j["mode"])
        for waiting in ordered:
            if (waiting["finish_ms"] is not None or waiting["failed"] or waiting["mode"] or
                    now < waiting.get("release_ms", 0) or now < waiting["ack_until_ms"]):
                continue
            minimum_power = min(waiting["modes_kw"].values()) if mode_choice else max(waiting["modes_kw"].values())
            if active_power + minimum_power <= min(true_capacity, reported_capacity) + 1e-9:
                continue
            eligible = [running for running in reversed(ordered)
                        if running["mode"] is not None and running.get("interruptible", False)
                        and running["deadline_ms"] > waiting["deadline_ms"]]
            if (active_power - sum(r["modes_kw"][r["mode"]] for r in eligible)
                    + minimum_power > min(true_capacity, reported_capacity) + 1e-9):
                continue  # do not stop a device when preemption cannot help
            for running in eligible:
                active_power -= running["modes_kw"][running["mode"]]
                running["mode"] = None
                running["ack_until_ms"] = now + running["stop_ack_ms"]
                running["remaining_kws"] += running["resume_loss_kws"]
                running["pause_count"] += 1
                events.append({"at_ms": now, "type": "voluntary_pause",
                               "job_id": running["id"],
                               "stop_ack_at_ms": running["ack_until_ms"]})
                if active_power + minimum_power <= min(true_capacity, reported_capacity) + 1e-9:
                    break
        for job in ordered:
            if (job["finish_ms"] is not None or job["failed"] or job["mode"] or now < job["ack_until_ms"]
                    or now < job.get("release_ms", 0)
                    or job["blocked_report_version"] == report_version):
                continue
            choices = sorted(job["modes_kw"].items(), key=lambda x: -x[1])
            if not mode_choice:
                choices = choices[:1]
            else:
                choices.reverse()  # explicit conservative mode selector for this probe
            for mode, power in choices:
                if active_power + power > reported_capacity + 1e-9:
                    continue
                if active_power + power > true_capacity + 1e-9:
                    gate_rejections += 1
                    job["blocked_report_version"] = report_version
                    events.append({"at_ms": now, "type": "hardware_start_rejected",
                                   "job_id": job["id"], "mode": mode})
                    continue
                job["mode"] = mode
                job["started"] = True
                active_power += power
                events.append({"at_ms": now, "type": "start_acknowledged",
                               "job_id": job["id"], "mode": mode})
                break
        if active_power > true_capacity + 1e-9:
            raise AssertionError("hardware capacity invariant broken")
        peak_power = max(peak_power, active_power)
        for job in ordered:
            if not job["mode"]:
                continue
            job["remaining_kws"] -= job["modes_kw"][job["mode"]] * STEP_MS / 1000
            if job["remaining_kws"] <= 1e-9:
                job["finish_ms"] = now + STEP_MS
                job["mode"] = None
                events.append({"at_ms": now + STEP_MS, "type": "completed",
                               "job_id": job["id"]})
        if (all(j["finish_ms"] is not None or j["failed"] for j in ordered)
                and now >= capacity_events[-1]["at_ms"] and not pending_reports):
            break
    return {"mode_choice": mode_choice, "capacity_safe": True,
            "peak_power_kw": peak_power, "hardware_start_rejections": gate_rejections,
            "jobs": {j["id"]: {"finish_ms": j["finish_ms"],
                              "failed_after_trip": j["failed"],
                              "deadline_met": (j["finish_ms"] is not None and
                                               j["finish_ms"] <= j["deadline_ms"]),
                              "trip_count": j["trip_count"],
                              "pause_count": j["pause_count"],
                              "remaining_kws": round(max(0, j["remaining_kws"]), 3)}
                     for j in ordered}, "events": events}
