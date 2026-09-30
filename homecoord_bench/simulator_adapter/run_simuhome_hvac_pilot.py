"""Run the frozen HomeCoord HVAC adapter pilot against a local SimuHome API.

This records simulator-adapter behavior only. It does not call an LLM or a
physical device, and it does not claim calibrated household temperature.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "homecoord_bench" / "simulator_adapter" / "hvac_trial_inputs_v0.1.json"
TRACE_DIR = ROOT / "homecoord_bench" / "results" / "simuhome_hvac_pilot_traces"
SUMMARY_PATH = ROOT / "homecoord_bench" / "results" / "simuhome_hvac_pilot_20260927.json"
THERMAL_SUMMARY_PATH = ROOT / "homecoord_bench" / "results" / "simuhome_hvac_thermal_response_20260927.json"
BACKEND_REVISION = "83d28837b69f0cbf1bc02ed5334cb8b561a9d54d"
TRACE_SCHEMA = "simulator-adapter-trace-0.1"


class PilotError(RuntimeError):
    pass


class SimuHomeClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.latencies_ms: list[dict[str, Any]] = []

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PilotError(f"HTTP {exc.code} for {method} {path}: {detail}") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.latencies_ms.append({
            "method": method,
            "path": path,
            "adapter_wall_latency_ms": round(elapsed_ms, 3),
        })
        status = payload.get("status", {})
        if not isinstance(status, dict) or int(status.get("code", 500)) >= 400:
            raise PilotError(f"SimuHome returned an error for {method} {path}: {payload}")
        return payload


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def response_state(response: dict[str, Any], *, reset: bool = False) -> dict[str, Any]:
    data = response.get("data") or {}
    if reset:
        state = data.get("initial_home_config")
    else:
        state = data
    if not isinstance(state, dict) or not isinstance(state.get("current_tick"), int):
        raise PilotError(f"Response lacks a home state/current_tick: {response}")
    return state


def device_and_room(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    room = state["rooms"]["living_room"]
    device = next(
        item for item in room["devices"] if item["device_id"] == "homecoord_trial_hvac"
    )
    return device["attributes"], room["state"]


def metadata(
    run_id: str,
    scenario_id: str,
    schedule_id: str,
    tick_ms: int,
    expected_order: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": TRACE_SCHEMA,
        "run_id": run_id,
        "scenario_id": scenario_id,
        "schedule_id": schedule_id,
        "backend_revision": BACKEND_REVISION,
        "random_seed": 0,
        "tick_ms": tick_ms,
        "expected_proposal_order": expected_order,
    }


def add_event(
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    event_type: str,
    tick: int,
    **values: Any,
) -> None:
    events.append({
        **meta,
        "seq": len(events),
        "event_type": event_type,
        "homecoord_tick": tick,
        "backend_tick": tick,
        **values,
    })


def api_start_time(base_time: str, offset_seconds: int) -> str:
    parsed = datetime.strptime(base_time, "%Y-%m-%d %H:%M:%S")
    return (parsed + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def reset_run(client: SimuHomeClient, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.request("POST", "/simulation/reset", config)
    state = response_state(response, reset=True)
    if state["current_tick"] != 0:
        raise PilotError(f"reset did not begin at tick 0: {state['current_tick']}")
    attrs, room = device_and_room(state)
    if room.get("temperature") != attrs.get("1.Thermostat.LocalTemperature"):
        raise PilotError("reset room temperature and HVAC LocalTemperature are not aligned")
    return response, state


def schedule_proposal(
    client: SimuHomeClient,
    fixture: dict[str, Any],
    proposal_id: str,
    offset_seconds: int,
) -> tuple[dict[str, Any], int]:
    bundle = fixture["proposal_command_bundles"][proposal_id]
    interval = float(fixture["reset_config"]["tick_interval"])
    due_tick = int(math.ceil(offset_seconds / interval))
    response = client.request("POST", "/schedule/workflow", {
        "start_time": api_start_time(fixture["reset_config"]["base_time"], offset_seconds),
        "description": f"homecoord-{proposal_id}-{proposal_id}",
        "steps": bundle["steps"],
    })
    workflow_id = response.get("data", {}).get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise PilotError(f"workflow schedule did not return an id: {response}")
    return {"workflow_id": workflow_id, "response": response, "proposal_id": proposal_id}, due_tick


def check_workflow(client: SimuHomeClient, workflow: dict[str, Any]) -> dict[str, Any]:
    status = client.request("GET", f"/schedule/workflow/{workflow['workflow_id']}/status")
    data = status.get("data", {})
    expected_steps = len(workflow.get("steps", []))
    if data.get("status") != "completed":
        raise PilotError(f"workflow {workflow['workflow_id']} was not completed: {data}")
    if data.get("error") is not None:
        raise PilotError(f"workflow reported an error: {data}")
    if expected_steps and data.get("current_step") != expected_steps - 1:
        raise PilotError(f"workflow step count does not match: {data}")
    return data


def add_proposal_events(
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    proposal_id: str,
    due_tick: int,
    workflow: dict[str, Any],
    bundle_id: str,
    *,
    submit_tick: int = 0,
) -> None:
    add_event(
        events, meta, "proposal_scheduled", submit_tick,
        proposal_id=f"p-{proposal_id}",
        agent_id="ComfortAgent" if proposal_id == "cool" else "EnergyAgent",
        task_id=proposal_id,
        planned_execution_tick=due_tick,
        workflow_id=workflow["workflow_id"],
    )
    steps = workflow["steps"]
    for order, step in enumerate(steps):
        command_id = f"{workflow['workflow_id']}-step-{order}"
        args = step["args"]
        api_command = args.get("command_id") or args.get("attribute_id")
        add_event(
            events, meta, "command_submitted", submit_tick,
            proposal_id=f"p-{proposal_id}",
            command_bundle_id=bundle_id,
            command_id=command_id,
            command_order=order,
            command_name=api_command,
            tool=step["tool"],
            planned_execution_tick=due_tick,
            workflow_id=workflow["workflow_id"],
        )
        workflow["command_ids"].append(command_id)


def add_workflow_results(
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    proposal_id: str,
    due_tick: int,
    workflow: dict[str, Any],
    bundle_id: str,
    execution_start: int,
    status: dict[str, Any],
) -> int:
    for order, command_id in enumerate(workflow["command_ids"]):
        add_event(
            events, meta, "command_result", due_tick,
            proposal_id=f"p-{proposal_id}",
            command_bundle_id=bundle_id,
            command_id=command_id,
            status="completed",
            execution_order=execution_start + order,
            order_evidence="backend_ack",
            result_source="completed_workflow_status",
            workflow_status=copy.deepcopy(status),
            workflow_step_order=order,
        )
    return execution_start + len(workflow["command_ids"])


def add_snapshot(
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    state: dict[str, Any],
    *,
    final: bool = False,
    reason: str,
) -> str:
    tick = int(state["current_tick"])
    digest = canonical_digest(state)
    add_event(
        events, meta, "state_snapshot", tick,
        state_digest=digest,
        is_final=final,
        snapshot_reason=reason,
        raw_backend_state=copy.deepcopy(state),
    )
    return digest


def write_trace(events: list[dict[str, Any]], run_id: str, trace_dir: Path = TRACE_DIR) -> Path:
    for index, event in enumerate(events):
        event["seq"] = index
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{run_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    return path


def run_a(client: SimuHomeClient, fixture: dict[str, Any], repetition: int) -> dict[str, Any]:
    latency_start = len(client.latencies_ms)
    run_id = f"A-r{repetition}"
    config = copy.deepcopy(fixture["reset_config"])
    interval = float(config["tick_interval"])
    due_tick = int(math.ceil(2 / interval))
    target_tick = due_tick + 5
    meta = metadata(run_id, "simuhome-hvac-reset-cool", "cool-at-t20", int(interval * 1000), ["p-cool"])
    events: list[dict[str, Any]] = []
    reset_response, initial = reset_run(client, config)
    initial_digest = canonical_digest(initial)
    add_event(events, meta, "reset", 0, state_digest=initial_digest, raw_backend_state=initial,
              reset_response=reset_response)
    workflow, _ = schedule_proposal(client, fixture, "cool", 2)
    workflow["steps"] = fixture["proposal_command_bundles"]["cool"]["steps"]
    workflow["command_ids"] = []
    add_proposal_events(events, meta, "cool", due_tick, workflow, f"{run_id}-cool")
    ff = client.request("POST", "/simulation/fast_forward_to", {"to_tick": target_tick})
    final = response_state(ff)
    if final["current_tick"] != target_tick:
        raise PilotError(f"A requested tick {target_tick} but backend returned {final['current_tick']}")
    status = check_workflow(client, workflow)
    execution_end = add_workflow_results(events, meta, "cool", due_tick, workflow,
                                         f"{run_id}-cool", 0, status)
    attrs, room = device_and_room(final)
    expected = (
        attrs.get("1.OnOff.OnOff") is True
        and attrs.get("1.Thermostat.SystemMode") == 3
        and attrs.get("1.Thermostat.OccupiedCoolingSetpoint") == 2400
        and attrs.get("1.FanControl.PercentSetting") == 66
    )
    if not expected:
        raise PilotError(f"A did not reach the expected HVAC state: {attrs}")
    final_digest = add_snapshot(events, meta, final, final=True, reason="fast_forward_target")
    add_event(events, meta, "run_finished", target_tick, state_digest=final_digest,
              completed_workflows=[status])
    trace_path = write_trace(events, run_id)
    return {
        "run_id": run_id,
        "card": "A",
        "scenario_id": meta["scenario_id"],
        "schedule_id": meta["schedule_id"],
        "trace_path": str(trace_path.relative_to(ROOT)),
        "reset_initial_state_digest": initial_digest,
        "final_state_digest": final_digest,
        "final_tick": final["current_tick"],
        "workflow_status": status,
        "final_attributes": attrs,
        "room_state": room,
        "room_temperature_delta_raw": room.get("temperature", 0) - initial["rooms"]["living_room"]["state"]["temperature"],
        "pass": expected and status.get("status") == "completed",
        "api_wall_latencies": copy.deepcopy(client.latencies_ms[latency_start:]),
    }


def run_b(client: SimuHomeClient, fixture: dict[str, Any], schedule_id: str, repetition: int) -> dict[str, Any]:
    latency_start = len(client.latencies_ms)
    run_id = f"B-{schedule_id}-r{repetition}"
    config = copy.deepcopy(fixture["reset_config"])
    interval = float(config["tick_interval"])
    first_tick = int(math.ceil(1 / interval))
    second_tick = int(math.ceil(2 / interval))
    midpoint_tick = first_tick + 5
    final_tick = second_tick + 5
    order = ["cool", "off"] if schedule_id == "cool-then-off" else ["off", "cool"]
    proposal_order = [f"p-{value}" for value in order]
    meta = metadata(run_id, "simuhome-hvac-opposite-proposal-order", schedule_id,
                    int(interval * 1000), proposal_order)
    events: list[dict[str, Any]] = []
    reset_response, initial = reset_run(client, config)
    initial_digest = canonical_digest(initial)
    add_event(events, meta, "reset", 0, state_digest=initial_digest, raw_backend_state=initial,
              reset_response=reset_response)

    workflow_pairs = []
    for proposal_id, offset, due_tick in ((order[0], 1, first_tick), (order[1], 2, second_tick)):
        workflow, _ = schedule_proposal(client, fixture, proposal_id, offset)
        workflow["steps"] = fixture["proposal_command_bundles"][proposal_id]["steps"]
        workflow["command_ids"] = []
        add_proposal_events(events, meta, proposal_id, due_tick, workflow, f"{run_id}-{proposal_id}")
        workflow_pairs.append((proposal_id, due_tick, workflow, f"{run_id}-{proposal_id}"))

    mid_response = client.request("POST", "/simulation/fast_forward_to", {"to_tick": midpoint_tick})
    midpoint = response_state(mid_response)
    if midpoint["current_tick"] != midpoint_tick:
        raise PilotError(f"B midpoint requested {midpoint_tick}, got {midpoint['current_tick']}")
    first_status = check_workflow(client, workflow_pairs[0][2])
    add_workflow_results(events, meta, workflow_pairs[0][0], workflow_pairs[0][1],
                         workflow_pairs[0][2], workflow_pairs[0][3], 0, first_status)
    mid_digest = add_snapshot(events, meta, midpoint, reason="after_first_proposal")

    final_response = client.request("POST", "/simulation/fast_forward_to", {"to_tick": final_tick})
    final = response_state(final_response)
    if final["current_tick"] != final_tick:
        raise PilotError(f"B final tick requested {final_tick}, got {final['current_tick']}")
    second_status = check_workflow(client, workflow_pairs[1][2])
    second_start = len(workflow_pairs[0][2]["command_ids"])
    add_workflow_results(events, meta, workflow_pairs[1][0], workflow_pairs[1][1],
                         workflow_pairs[1][2], workflow_pairs[1][3], second_start, second_status)
    attrs, room = device_and_room(final)
    expected_on = schedule_id == "off-then-cool"
    expected = attrs.get("1.OnOff.OnOff") is expected_on
    if not expected:
        raise PilotError(f"B final state does not match order {schedule_id}: {attrs}")
    final_digest = add_snapshot(events, meta, final, final=True, reason="after_second_proposal")
    add_event(events, meta, "run_finished", final_tick, state_digest=final_digest,
              completed_workflows=[first_status, second_status])
    trace_path = write_trace(events, run_id)
    return {
        "run_id": run_id,
        "card": "B",
        "scenario_id": meta["scenario_id"],
        "schedule_id": schedule_id,
        "expected_proposal_order": proposal_order,
        "trace_path": str(trace_path.relative_to(ROOT)),
        "reset_initial_state_digest": initial_digest,
        "mid_state_digest": mid_digest,
        "final_state_digest": final_digest,
        "mid_tick": midpoint["current_tick"],
        "final_tick": final["current_tick"],
        "workflow_statuses": [first_status, second_status],
        "final_attributes": attrs,
        "room_state": room,
        "room_temperature_delta_raw": room.get("temperature", 0) - initial["rooms"]["living_room"]["state"]["temperature"],
        "pass": expected and all(item.get("status") == "completed" for item in (first_status, second_status)),
        "api_wall_latencies": copy.deepcopy(client.latencies_ms[latency_start:]),
    }


def run_c(client: SimuHomeClient, fixture: dict[str, Any], repetition: int) -> dict[str, Any]:
    latency_start = len(client.latencies_ms)
    run_id = f"C-r{repetition}"
    config = copy.deepcopy(fixture["reset_config"])
    config["tick_interval"] = 1.0
    interval = 1.0
    meta = metadata(run_id, "simuhome-clock-step", "single-step-fast-forward", 1000, [])
    events: list[dict[str, Any]] = []
    reset_response, initial = reset_run(client, config)
    initial_digest = canonical_digest(initial)
    add_event(events, meta, "reset", 0, state_digest=initial_digest, raw_backend_state=initial,
              reset_response=reset_response)
    snapshots: list[dict[str, Any]] = []
    prior_tick = 0
    for target in (1, 2, 3):
        response = client.request("POST", "/simulation/fast_forward_to", {"to_tick": target})
        state = response_state(response)
        actual = int(state["current_tick"])
        if actual != target:
            raise PilotError(f"C requested tick {target} but observed tick {actual}")
        add_event(events, meta, "tick_advanced", actual, previous_backend_tick=prior_tick,
                  observed_virtual_time=state.get("current_time"), tick_interval_seconds=interval)
        digest = add_snapshot(events, meta, state, reason="one_step_clock_probe")
        snapshots.append({"tick": actual, "digest": digest, "virtual_time": state.get("current_time")})
        prior_tick = actual
    final_digest = snapshots[-1]["digest"]
    add_event(events, meta, "run_finished", prior_tick, state_digest=final_digest,
              clock_steps=snapshots)
    trace_path = write_trace(events, run_id)
    return {
        "run_id": run_id,
        "card": "C",
        "scenario_id": meta["scenario_id"],
        "schedule_id": meta["schedule_id"],
        "trace_path": str(trace_path.relative_to(ROOT)),
        "reset_initial_state_digest": initial_digest,
        "clock_steps": snapshots,
        "final_state_digest": final_digest,
        "pass": [item["tick"] for item in snapshots] == [1, 2, 3],
        "api_wall_latencies": copy.deepcopy(client.latencies_ms[latency_start:]),
    }


def run_d(client: SimuHomeClient, fixture: dict[str, Any], repetition: int) -> dict[str, Any]:
    """Short no-command control matched to A's tick-25 endpoint."""
    latency_start = len(client.latencies_ms)
    run_id = f"D-idle-control-r{repetition}"
    config = copy.deepcopy(fixture["reset_config"])
    target_tick = 25
    meta = metadata(run_id, "simuhome-hvac-idle-control", "no-command-to-t25", 100, [])
    events: list[dict[str, Any]] = []
    reset_response, initial = reset_run(client, config)
    initial_digest = canonical_digest(initial)
    add_event(events, meta, "reset", 0, state_digest=initial_digest,
              raw_backend_state=initial, reset_response=reset_response)
    response = client.request("POST", "/simulation/fast_forward_to", {"to_tick": target_tick})
    final = response_state(response)
    if final["current_tick"] != target_tick:
        raise PilotError(f"D requested tick {target_tick} but backend returned {final['current_tick']}")
    attrs, room = device_and_room(final)
    if attrs.get("1.OnOff.OnOff") is not False:
        raise PilotError("D no-command control unexpectedly turned on HVAC")
    final_digest = add_snapshot(events, meta, final, final=True, reason="no_op_idle_control")
    add_event(events, meta, "run_finished", target_tick, state_digest=final_digest)
    trace_path = write_trace(events, run_id)
    delta = room.get("temperature", 0) - initial["rooms"]["living_room"]["state"]["temperature"]
    return {
        "run_id": run_id,
        "card": "D",
        "scenario_id": meta["scenario_id"],
        "schedule_id": meta["schedule_id"],
        "trace_path": str(trace_path.relative_to(ROOT)),
        "reset_initial_state_digest": initial_digest,
        "final_state_digest": final_digest,
        "final_tick": final["current_tick"],
        "final_attributes": attrs,
        "room_state": room,
        "room_temperature_delta_raw": delta,
        "pass": delta == 0.0,
        "api_wall_latencies": copy.deepcopy(client.latencies_ms[latency_start:]),
    }


def run_e(
    client: SimuHomeClient,
    fixture: dict[str, Any],
    condition: str,
    repetition: int,
) -> dict[str, Any]:
    """One virtual hour, comparing passive drift with active cooling."""
    latency_start = len(client.latencies_ms)
    run_id = f"E-{condition}-r{repetition}"
    config = copy.deepcopy(fixture["reset_config"])
    due_tick = 20
    target_tick = 36_000
    proposal_order = ["p-cool"] if condition == "cool" else []
    meta = metadata(run_id, "simuhome-hvac-thermal-response", f"{condition}-one-virtual-hour", 100,
                    proposal_order)
    events: list[dict[str, Any]] = []
    reset_response, initial = reset_run(client, config)
    initial_digest = canonical_digest(initial)
    add_event(events, meta, "reset", 0, state_digest=initial_digest,
              raw_backend_state=initial, reset_response=reset_response)

    workflow = None
    if condition == "cool":
        workflow, _ = schedule_proposal(client, fixture, "cool", 2)
        workflow["steps"] = fixture["proposal_command_bundles"]["cool"]["steps"]
        workflow["command_ids"] = []
        add_proposal_events(events, meta, "cool", due_tick, workflow, f"{run_id}-cool")

    response = client.request("POST", "/simulation/fast_forward_to", {"to_tick": target_tick})
    final = response_state(response)
    if final["current_tick"] != target_tick:
        raise PilotError(f"E requested tick {target_tick} but backend returned {final['current_tick']}")
    completed_workflows = []
    if workflow is not None:
        status = check_workflow(client, workflow)
        add_workflow_results(events, meta, "cool", due_tick, workflow,
                             f"{run_id}-cool", 0, status)
        completed_workflows.append(status)

    attrs, room = device_and_room(final)
    expected_on = condition == "cool"
    if attrs.get("1.OnOff.OnOff") is not expected_on:
        raise PilotError(f"E {condition} ended in unexpected HVAC state: {attrs}")
    delta = room.get("temperature", 0) - initial["rooms"]["living_room"]["state"]["temperature"]
    if condition == "cool" and delta >= 0:
        raise PilotError(f"E active cooling did not lower room state: delta={delta}")
    if condition == "idle" and delta != 0.0:
        raise PilotError(f"E idle baseline drifted unexpectedly: delta={delta}")

    final_digest = add_snapshot(events, meta, final, final=True, reason="one_virtual_hour_endpoint")
    add_event(events, meta, "run_finished", target_tick, state_digest=final_digest,
              completed_workflows=completed_workflows)
    trace_path = write_trace(events, run_id)
    return {
        "run_id": run_id,
        "card": "E",
        "condition": condition,
        "scenario_id": meta["scenario_id"],
        "schedule_id": meta["schedule_id"],
        "trace_path": str(trace_path.relative_to(ROOT)),
        "reset_initial_state_digest": initial_digest,
        "final_state_digest": final_digest,
        "final_tick": final["current_tick"],
        "virtual_time": final.get("current_time"),
        "workflow_statuses": completed_workflows,
        "final_attributes": attrs,
        "room_state": room,
        "room_temperature_delta_raw": delta,
        "pass": True,
        "api_wall_latencies": copy.deepcopy(client.latencies_ms[latency_start:]),
    }


def run_all(base_url: str) -> dict[str, Any]:
    fixture = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    client = SimuHomeClient(base_url)
    client.request("GET", "/__health__")
    results: list[dict[str, Any]] = []
    for repetition in range(1, 4):
        results.append(run_a(client, fixture, repetition))
    for schedule_id in ("cool-then-off", "off-then-cool"):
        for repetition in range(1, 4):
            results.append(run_b(client, fixture, schedule_id, repetition))
    for repetition in range(1, 4):
        results.append(run_c(client, fixture, repetition))
    for repetition in range(1, 4):
        results.append(run_d(client, fixture, repetition))
    thermal_results = []
    for condition in ("idle", "cool"):
        for repetition in range(1, 4):
            result = run_e(client, fixture, condition, repetition)
            results.append(result)
            thermal_results.append(result)
    THERMAL_SUMMARY_PATH.write_text(json.dumps({
        "schema_version": "simuhome-hvac-thermal-response-0.1",
        "date": "2026-09-27",
        "backend_revision": BACKEND_REVISION,
        "horizon": {"tick_interval_seconds": 0.1, "target_tick": 36_000, "virtual_duration_seconds": 3600},
        "temperature_scale_calibrated": False,
        "results": thermal_results,
        "interpretation": (
            "A one-hour internal simulator probe: no-command controls and repeated cooling traces. "
            "This tests deterministic response in this backend, not calibration against real homes."
        ),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "schema_version": "simuhome-hvac-pilot-summary-0.1",
        "date": "2026-09-27",
        "backend": {
            "name": "SimuHome",
            "commit": BACKEND_REVISION,
            "base_url": base_url,
            "upstream_source_modified": False,
        },
        "method": {
            "models_called": 0,
            "physical_devices_used": 0,
            "initial_temperature_raw": 2900,
            "temperature_units_calibrated": False,
            "trial_count": len(results),
            "cards": {"A": 3, "B_cool_then_off": 3, "B_off_then_cool": 3,
                      "C": 3, "D_idle_control": 3, "E_one_hour_idle": 3, "E_one_hour_cool": 3},
            "note": (
                "Local fixed-configuration adapter pilot only. temperature_delta_raw is in the simulator's "
                "unvalidated internal scale; command workflow API timing is not Agent/model latency."
            ),
        },
        "results": results,
        "passed_count": sum(bool(item.get("pass")) for item in results),
        "failed_count": sum(not bool(item.get("pass")) for item in results),
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("HOMECOORD_SIMUHOME_BASE_URL", "http://127.0.0.1:8765/api"),
    )
    args = parser.parse_args()
    result = run_all(args.base_url)
    print(json.dumps({
        "summary_path": str(SUMMARY_PATH),
        "trial_count": result["method"]["trial_count"],
        "passed_count": result["passed_count"],
        "failed_count": result["failed_count"],
        "runs": [{"run_id": item["run_id"], "pass": item["pass"], "trace_path": item["trace_path"]}
                 for item in result["results"]],
    }, ensure_ascii=False, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
