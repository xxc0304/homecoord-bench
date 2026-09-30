"""Replay one saved HomeCoord C1-HVAC proposal pair into SimuHome.

The model decisions and measured logical API times are read from an existing
local exploratory run. This script makes no model API calls and controls no
physical devices.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from run_simuhome_hvac_pilot import (
    BACKEND_REVISION,
    INPUT_PATH,
    ROOT,
    TRACE_DIR,
    PilotError,
    SimuHomeClient,
    add_event,
    add_snapshot,
    canonical_digest,
    device_and_room,
    metadata,
    reset_run,
    response_state,
    write_trace,
)


PROBE_PATH = ROOT / "homecoord_bench" / "results" / "paired_task_batch_v1_probe.json"
CONFLICT_EPISODE_PATH = ROOT / "homecoord_bench" / "data" / "pilot_pairs_v1" / "HC-PAIR-C1-HVAC-CONFLICT.json"
CONTROL_EPISODE_PATH = ROOT / "homecoord_bench" / "data" / "pilot_pairs_v1" / "HC-PAIR-C1-HVAC-CONTROL.json"
OUTPUT_PATH = ROOT / "homecoord_bench" / "results" / "homecoord_hvac_pair_simuhome_replay_20260927.json"
PAIR_TRACE_DIR = ROOT / "homecoord_bench" / "results" / "homecoord_hvac_pair_simuhome_replay_traces"
INSTRUCTIONS = "Replay the saved, already-validated action proposal as recorded."
REPETITIONS = 3


class SavedDecisionClient:
    """Serve saved model decisions and expose their measured logical latency."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = copy.deepcopy(records)
        self.index = 0
        self.last_latency_ms = 0

    def decide(self, request: dict[str, Any], instructions: str) -> dict[str, Any]:
        if self.index >= len(self.records):
            raise PilotError("HomeCoord requested more decisions than the saved record contains")
        record = self.records[self.index]
        self.index += 1
        self.last_latency_ms = int(record["logical_latency_ms"])
        return copy.deepcopy(record["decision"])

    def assert_consumed(self) -> None:
        if self.index != len(self.records):
            raise PilotError(f"HomeCoord consumed {self.index}/{len(self.records)} saved decisions")


def load_saved_records() -> dict[str, Any]:
    payload = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
    row = next(
        item for item in payload["rows"]
        if item.get("pair_id") == "C1-HVAC" and item.get("repetition") == 1
    )
    if row.get("error") or "model_records" not in row:
        raise PilotError(f"Saved C1-HVAC record is incomplete: {row}")
    return row


def generate_homecoord_trace(episode: dict[str, Any], saved: dict[str, Any], architecture: str, condition: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from runtime.execution import run_closed_loop_episode

    records = saved["model_records"]
    selected = (
        [records["first_conflict"], records["shared_local"]]
        if condition == "conflict"
        else [records["first_control"], records["shared_local"]]
    )
    client = SavedDecisionClient(selected)
    trace, metrics = run_closed_loop_episode(
        episode, client, architecture, INSTRUCTIONS, synthetic_latency=False
    )
    client.assert_consumed()
    accepted = sorted(
        (event for event in trace["events"] if event.get("type") == "action_effective"),
        key=lambda event: (event["timestamp_ms"], event["task_id"]),
    )
    return trace, metrics, accepted


def endpoint_command(client: SimuHomeClient, base: str, endpoint: int, cluster: str, command: str) -> dict[str, Any]:
    return client.request("POST", f"/devices/homecoord_trial_hvac/commands", {
        "endpoint_id": endpoint,
        "cluster_id": cluster,
        "command_id": command,
        "args": {},
    })


def endpoint_attribute(client: SimuHomeClient, cluster: str, attribute: str, value: Any) -> dict[str, Any]:
    return client.request("POST", "/devices/homecoord_trial_hvac/attributes/write", {
        "endpoint_id": 1,
        "cluster_id": cluster,
        "attribute_id": attribute,
        "value": value,
    })


def read_home(client: SimuHomeClient) -> dict[str, Any]:
    return client.request("GET", "/home/state")


def apply_homecoord_action(
    client: SimuHomeClient,
    action: dict[str, Any],
    target_tick: int,
    origin_tick: int,
    *,
    proposal_id: str,
    bundle_id: str,
    meta: dict[str, Any],
    events: list[dict[str, Any]],
    start_execution_order: int,
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    advance = client.request("POST", "/simulation/fast_forward_to", {"to_tick": target_tick})
    state_at_target = response_state(advance)
    if state_at_target["current_tick"] != target_tick:
        raise PilotError(
            f"Could not align HomeCoord action at {target_tick}: backend tick is {state_at_target['current_tick']}"
        )

    operation = action["operation"]
    if operation == "cool":
        commands = [
            ("execute_command", "OnOff", "On", None),
            ("write_attribute", "Thermostat", "SystemMode", 3),
            ("write_attribute", "Thermostat", "OccupiedCoolingSetpoint", 2400),
            ("write_attribute", "FanControl", "PercentSetting", 66),
        ]
    elif operation == "off":
        commands = [("execute_command", "OnOff", "Off", None)]
    else:
        raise PilotError(f"Unsupported saved HomeCoord HVAC action: {operation}")

    observed_steps: list[dict[str, Any]] = []
    next_execution_order = start_execution_order
    for order, (tool, cluster, name, value) in enumerate(commands):
        command_id = f"{bundle_id}-step-{order}"
        before = read_home(client)
        before_state = response_state(before)
        submit_tick = int(before_state["current_tick"])
        add_event(
            events, meta, "command_submitted", submit_tick,
            proposal_id=proposal_id,
            command_bundle_id=bundle_id,
            command_id=command_id,
            command_order=order,
            command_name=name,
            requested_by_action=operation,
            logical_action_timestamp_ms=action["timestamp_ms"],
        )
        if tool == "execute_command":
            receipt = endpoint_command(client, "/api", 1, cluster, name)
        else:
            receipt = endpoint_attribute(client, cluster, name, value)
        observed = read_home(client)
        observed_state = response_state(observed)
        observed_tick = int(observed_state["current_tick"])
        execution_tick = max(submit_tick, observed_tick - 1)
        attrs, _ = device_and_room(observed_state)
        step_ok = receipt.get("status", {}).get("code") == 200
        if tool == "execute_command" and name == "On":
            step_ok = step_ok and attrs.get("1.OnOff.OnOff") is True
        if tool == "execute_command" and name == "Off":
            step_ok = step_ok and attrs.get("1.OnOff.OnOff") is False
        if tool == "write_attribute":
            step_ok = step_ok and attrs.get(f"1.{cluster}.{name}") == value
        if not step_ok:
            raise PilotError(f"HomeCoord action step did not stick: {name}; receipt={receipt}; attrs={attrs}")

        add_event(
            events, meta, "command_result", execution_tick,
            proposal_id=proposal_id,
            command_bundle_id=bundle_id,
            command_id=command_id,
            status="completed",
            execution_order=next_execution_order,
            order_evidence="backend_ack",
            backend_receipt=receipt,
            observed_tick=observed_tick,
        )
        digest = add_snapshot(events, meta, observed_state, reason=f"after_{operation}_{name}")
        observed_steps.append({
            "command_name": name,
            "requested_tick": target_tick,
            "submit_tick": submit_tick,
            "execution_tick_estimate": execution_tick,
            "observation_tick": observed_tick,
            "state_digest": digest,
            "backend_receipt": receipt.get("data"),
        })
        next_execution_order += 1
    final_state = response_state(read_home(client))
    return final_state, next_execution_order, observed_steps


def one_run(base_url: str, episode: dict[str, Any], saved: dict[str, Any], condition: str,
            architecture: str, repetition: int) -> dict[str, Any]:
    from runtime.execution import DEVICE_DELAY_MS

    run_id = f"F-{condition}-{architecture}-r{repetition}"
    trace_id = "conflict" if condition == "conflict" else "control"
    homecoord_trace, homecoord_metrics, actions = generate_homecoord_trace(
        episode, saved, architecture, condition
    )
    expected_order = [f"p-{event['proposal_id']}" for event in actions]
    meta = metadata(run_id, "homecoord-hvac-pair-replay", f"{condition}-{architecture}", 1, expected_order)
    simuhome = SimuHomeClient(base_url)
    fixture = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    config = copy.deepcopy(fixture["reset_config"])
    config["tick_interval"] = 0.001
    reset_response, initial = reset_run(simuhome, config)
    origin_tick = int(initial["current_tick"])
    initial_digest = canonical_digest(initial)
    events: list[dict[str, Any]] = []
    add_event(events, meta, "reset", origin_tick,
              state_digest=initial_digest, raw_backend_state=initial,
              reset_response=reset_response,
              homecoord_episode_id=episode["episode_id"],
              saved_model="deepseek-flash",
              saved_model_records_source=str(PROBE_PATH.relative_to(ROOT)))

    task_lookup = {item["task_id"]: item for item in episode["task_stream"]}
    for event in actions:
        task = task_lookup[event["task_id"]]
        add_event(
            events, meta, "proposal_scheduled", origin_tick + int(task["release_at_ms"]),
            proposal_id=f"p-{event['proposal_id']}",
            agent_id=event["agent_id"],
            task_id=event["task_id"],
            release_at_ms=task["release_at_ms"],
            saved_model_latency_ms=event["timestamp_ms"] - task["release_at_ms"] - DEVICE_DELAY_MS,
            homecoord_action_timestamp_ms=event["timestamp_ms"],
            operation=event["operation"],
        )

    next_execution_order = 0
    action_results = []
    simuhome_action_state = None
    for event in actions:
        action_timestamp = int(event["timestamp_ms"])
        target_tick = origin_tick + action_timestamp
        pid = f"p-{event['proposal_id']}"
        bundle_id = f"{run_id}-{event['task_id']}"
        state, next_execution_order, steps = apply_homecoord_action(
            simuhome,
            event,
            target_tick,
            origin_tick,
            proposal_id=pid,
            bundle_id=bundle_id,
            meta=meta,
            events=events,
            start_execution_order=next_execution_order,
        )
        attrs, room = device_and_room(state)
        simuhome_action_state = state
        action_results.append({
            "task_id": event["task_id"],
            "agent_id": event["agent_id"],
            "proposal_id": event["proposal_id"],
            "operation": event["operation"],
            "homecoord_timestamp_ms": action_timestamp,
            "requested_backend_tick": target_tick,
            "completion_time_ms": action_timestamp + event["duration_ms"],
            "device_state_after_bundle": {
                "on": attrs.get("1.OnOff.OnOff"),
                "system_mode": attrs.get("1.Thermostat.SystemMode"),
                "cooling_setpoint_raw": attrs.get("1.Thermostat.OccupiedCoolingSetpoint"),
                "fan_percent": attrs.get("1.FanControl.PercentSetting"),
                "room_temperature_raw": room.get("temperature"),
            },
            "command_steps": steps,
        })

    if not actions:
        raise PilotError("saved HomeCoord policy produced no action; no simulator replay to evaluate")

    final_tick = origin_tick + max(
        int(event["timestamp_ms"]) + int(event["duration_ms"]) for event in actions
    )
    final_response = simuhome.request("POST", "/simulation/fast_forward_to", {"to_tick": final_tick})
    final_state = response_state(final_response)
    if final_state["current_tick"] != final_tick:
        raise PilotError(f"final HomeCoord replay tick {final_tick} was not reached")
    final_attrs, final_room = device_and_room(final_state)
    final_digest = add_snapshot(events, meta, final_state, final=True, reason="latest_accepted_action_end")
    add_event(events, meta, "run_finished", final_tick, state_digest=final_digest,
              homecoord_policy_metrics=homecoord_metrics)
    trace_path = write_trace(events, run_id, PAIR_TRACE_DIR)

    temp_raw = final_room.get("temperature")
    temp_c_by_internal_scale = temp_raw / 100.0 if isinstance(temp_raw, (float, int)) else None
    if trace_id == "conflict" and condition == "conflict":
        physical_target_satisfied = (
            final_attrs.get("1.OnOff.OnOff") is True
            and temp_c_by_internal_scale is not None
            and 23.0 <= temp_c_by_internal_scale <= 25.0
        )
    elif condition == "control":
        physical_target_satisfied = final_attrs.get("1.OnOff.OnOff") is False
    else:
        physical_target_satisfied = False

    expected_hvac_on = condition == "conflict" and architecture == "ConstraintCoordinator"
    return {
        "run_id": run_id,
        "condition": condition,
        "architecture": architecture,
        "repetition": repetition,
        "episode_id": episode["episode_id"],
        "pair_condition": episode.get("pair_condition"),
        "homecoord_trace_id": homecoord_trace["trace_id"],
        "trace_path": str(trace_path.relative_to(ROOT)),
        "reset_initial_digest": initial_digest,
        "final_state_digest": final_digest,
        "backend_revision": BACKEND_REVISION,
        "backend_tick_ms": 1,
        "clock_origin_tick": origin_tick,
        "final_tick": final_tick,
        "homecoord": {
            key: homecoord_metrics.get(key)
            for key in (
                "final_goal_success", "process_valid_success", "conflict_counts",
                "task_service", "task_action_finish_time_ms", "first_effective_action_latency_ms",
            )
        },
        "homecoord_coordination_decisions": [
            event for event in homecoord_trace["events"] if event.get("type") == "coordination_decision"
        ],
        "replayed_actions": action_results,
        "simuhome_final_state": {
            "hvac_on": final_attrs.get("1.OnOff.OnOff"),
            "system_mode": final_attrs.get("1.Thermostat.SystemMode"),
            "cooling_setpoint_raw": final_attrs.get("1.Thermostat.OccupiedCoolingSetpoint"),
            "room_temperature_raw": temp_raw,
            "room_temperature_c_by_internal_scale": temp_c_by_internal_scale,
        },
        "simuhome_physical_goal_proxy_satisfied": physical_target_satisfied,
        "interpretation": (
            "Backend state replay of saved HomeCoord actions. The HomeCoord evaluator applies action effects at start; "
            "SimuHome evolves HVAC room state over time. Raw thermal values are uncalibrated."
        ),
        "pass": final_attrs.get("1.OnOff.OnOff") is expected_hvac_on,
    }


def run(base_url: str) -> dict[str, Any]:
    import sys

    bench_root = ROOT / "homecoord_bench"
    if str(bench_root) not in sys.path:
        sys.path.insert(0, str(bench_root))
    saved = load_saved_records()
    episodes = {
        "conflict": json.loads(CONFLICT_EPISODE_PATH.read_text(encoding="utf-8")),
        "control": json.loads(CONTROL_EPISODE_PATH.read_text(encoding="utf-8")),
    }
    # Probe the local API once before mutating the single simulator instance.
    SimuHomeClient(base_url).request("GET", "/__health__")
    rows = []
    for condition in ("conflict", "control"):
        for architecture in ("IndependentMultiAgent", "ConstraintCoordinator"):
            for repetition in range(1, REPETITIONS + 1):
                rows.append(one_run(base_url, episodes[condition], saved, condition, architecture, repetition))
    summary = {
        "schema_version": "homecoord-hvac-simuhome-replay-0.1",
        "date": "2026-09-27",
        "source_model_records": {
            "path": str(PROBE_PATH.relative_to(ROOT)),
            "pair_id": "C1-HVAC",
            "repetition": 1,
            "model": "deepseek-flash",
            "models_called_during_this_replay": 0,
        },
        "backend": {"name": "SimuHome", "commit": BACKEND_REVISION,
                    "local_api_only": True, "physical_devices_used": 0},
        "mapping": {
            "homecoord_ms_to_backend_ticks": "1 logical millisecond = 1 SimuHome tick at 1 ms/tick",
            "cool": ["On", "SystemMode=3", "OccupiedCoolingSetpoint=2400", "PercentSetting=66"],
            "off": ["OnOff.Off"],
            "duration_note": "HomeCoord action duration is held in its event timeline; SimuHome commands change device state immediately.",
        },
        "rows": rows,
        "run_count": len(rows),
        "passed_count": sum(bool(row["pass"]) for row in rows),
        "failed_count": sum(not bool(row["pass"]) for row in rows),
    }
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765/api")
    args = parser.parse_args()
    result = run(args.base_url)
    print(json.dumps({
        "output_path": str(OUTPUT_PATH),
        "runs": result["run_count"],
        "passed": result["passed_count"],
        "failed": result["failed_count"],
        "rows": [{"run_id": row["run_id"], "homecoord_goal": row["homecoord"].get("final_goal_success"),
                  "physical_goal_proxy": row["simuhome_physical_goal_proxy_satisfied"],
                  "hvac_on": row["simuhome_final_state"]["hvac_on"],
                  "temp_raw": row["simuhome_final_state"]["room_temperature_raw"]}
                 for row in result["rows"]],
    }, ensure_ascii=False, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
