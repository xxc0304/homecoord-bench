"""Cross-check the revised C1 command states with fixed-version SimuHome.

HomeCoord supplies the timing category; SimuHome only checks the resulting
device state. The mapped seconds are symbolic and cannot measure real latency.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BENCH_ROOT.parent
sys.path.insert(0, str(BENCH_ROOT))

from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402
from run_simuhome_hvac_pilot import (  # noqa: E402
    BACKEND_REVISION, INPUT_PATH, SimuHomeClient, check_workflow,
    device_and_room, reset_run, response_state, schedule_proposal,
)

OUTPUT = BENCH_ROOT / "results" / "provenance_c1_simuhome_20260928.json"
DATA_DIR = BENCH_ROOT / "revision_drafts" / "20260928_provenance_pilot"
POLICIES = ("IndependentMultiAgent", "ConstraintCoordinator")


def _load_episodes() -> tuple[list[dict], dict[str, str]]:
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    episodes = []
    hashes = {}
    for condition in ("OVERLAP", "NONOVERLAP"):
        name = f"HC-PROV-C1-{condition}.json"
        content = (DATA_DIR / name).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != manifest["episode_sha256"][name]:
            raise RuntimeError(f"C1 input changed since manifest: {name}")
        episodes.append(json.loads(content.decode("utf-8")))
        hashes[name] = digest
    return episodes, hashes


def _one(client: SimuHomeClient, fixture: dict, episode: dict, policy: str, repetition: int) -> dict:
    trace, metrics = run_event_simulation(episode, DryRunClient(), policy, "")
    starts = sorted(
        (event for event in trace["events"] if event["type"] == "action_started"),
        key=lambda event: (event["timestamp_ms"], event["task_id"]),
    )
    if [event["operation"] for event in starts] != ["cool", "off"]:
        raise RuntimeError(f"C1 candidate had unexpected accepted actions: {starts}")
    off_start_ms = starts[1]["timestamp_ms"]
    off_slot_s = 2 if off_start_ms < 6000 else 8

    config = copy.deepcopy(fixture["reset_config"])
    config["tick_interval"] = 0.1
    _, initial = reset_run(client, config)
    if initial["current_tick"] != 0:
        raise RuntimeError("reset did not return tick zero")
    cool, _ = schedule_proposal(client, fixture, "cool", 1)
    off, _ = schedule_proposal(client, fixture, "off", off_slot_s)

    mid = response_state(client.request("POST", "/simulation/fast_forward_to", {"to_tick": 35}))
    mid_attrs, mid_room = device_and_room(mid)
    mid_cool_status = check_workflow(client, cool)
    mid_off_status = client.request(
        "GET", f"/schedule/workflow/{off['workflow_id']}/status"
    ).get("data", {})

    final = response_state(client.request("POST", "/simulation/fast_forward_to", {"to_tick": 95}))
    final_attrs, final_room = device_and_room(final)
    final_cool_status = check_workflow(client, cool)
    final_off_status = check_workflow(client, off)

    expected_mid_on = off_slot_s == 8
    passed = (
        mid_attrs.get("1.OnOff.OnOff") is expected_mid_on
        and final_attrs.get("1.OnOff.OnOff") is False
        and mid_cool_status.get("status") == "completed"
        and mid_off_status.get("status") == ("pending" if expected_mid_on else "completed")
        and final_cool_status.get("status") == "completed"
        and final_off_status.get("status") == "completed"
    )
    return {
        "episode_id": episode["episode_id"],
        "policy": policy,
        "repetition": repetition,
        "homecoord_cool_start_ms": starts[0]["timestamp_ms"],
        "homecoord_off_start_ms": off_start_ms,
        "symbolic_simuhome_cool_s": 1,
        "symbolic_simuhome_off_s": off_slot_s,
        "homecoord_process_valid_success": metrics["process_valid_success"],
        "homecoord_c1_conflict_count": metrics["conflict_counts"]["C1"],
        "mid_tick": mid["current_tick"],
        "mid_hvac_on": mid_attrs.get("1.OnOff.OnOff"),
        "mid_cool_workflow": mid_cool_status.get("status"),
        "mid_off_workflow": mid_off_status.get("status"),
        "final_tick": final["current_tick"],
        "final_hvac_on": final_attrs.get("1.OnOff.OnOff"),
        "final_cool_workflow": final_cool_status.get("status"),
        "final_off_workflow": final_off_status.get("status"),
        "room_temperature_raw_diagnostic_only": {
            "mid": mid_room.get("temperature"), "final": final_room.get("temperature")
        },
        "pass": passed,
    }


def run(base_url: str, repetitions: int = 2) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    fixture = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    episodes, source_hashes = _load_episodes()
    client = SimuHomeClient(base_url)
    client.request("GET", "/__health__")
    rows = [
        _one(client, fixture, episode, policy, repetition)
        for episode in episodes
        for policy in POLICIES
        for repetition in range(1, repetitions + 1)
    ]
    summary = {
        "status": "external_simulator_command_state_crosscheck_not_physical_calibration",
        "backend_revision": BACKEND_REVISION,
        "source_episodes": [episode["episode_id"] for episode in episodes],
        "source_episode_sha256": source_hashes,
        "mapping": "HomeCoord early/late off timing is mapped symbolically to SimuHome second 2/8; no millisecond latency equivalence",
        "models_called": 0,
        "physical_devices_used": 0,
        "rows": rows,
        "passed": sum(row["pass"] for row in rows),
        "total": len(rows),
    }
    OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765/api")
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    result = run(args.base_url, args.repetitions)
    print(json.dumps({"output": str(OUTPUT), "passed": result["passed"], "total": result["total"]},
                     ensure_ascii=False))
    if result["passed"] != result["total"]:
        raise SystemExit(1)
