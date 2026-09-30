"""Controlled paired action-choice probe, with a retry baseline.

Two existing scheduling structures, two opposite local requirement profiles.
Both supported service presets deliberately have equal resource costs to
isolate semantics from scheduling. These are synthetic service contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
from copy import deepcopy
from pathlib import Path
from statistics import median

from probe_c3_parallel_model_pilot import sample_parallel
from probe_c3_prospective_candidates_20260930 import load_locked
from probe_c3_structural_generalization import ScriptedProposalClient, latencies_for_order
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.event_simulator import run_event_simulation
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient
from runtime.scheduling_oracle import ideal_schedule
from runtime.tool_contract import validate_tool_call

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "revision_drafts" / "20260930_c3_action_choice"
OFFLINE = ROOT / "results" / "c3_action_choice_offline_20260930.json"
LIVE = ROOT / "results" / "c3_action_choice_model_20260930.json"
LOGDIR = ROOT / "runs" / "c3-action-choice-20260930"
PRESSURES = (0.8, 1.2, 1.6)
POLICIES = ("IndependentMultiAgent", "GateRetryRule", "ConstraintCoordinator",
            "DeadlineAwareCoordinator", "CapacityAwareDeadlineCoordinator")
PROFILES = ("P1A", "P1B", "P2A", "P2B")
PUBLIC = dict(zip(PROFILES, ("X17", "Q42", "M83", "V26")))
# Descriptions are synthetic API outcome contracts, not temperature physics.
MODES = {
    "heat_pump": (
        ("Deliver a warming service for this room.", "warming-service", "warming"),
        ("Deliver a cooling service for this room.", "cooling-service", "cooling")),
    "dishwasher": (
        ("Wash the ordinary dinner dishes; no hygiene treatment is requested.", "ordinary dish cleaning", "ordinary"),
        ("The baby feeding items need a hygiene treatment, not only ordinary cleaning.", "dish cleaning with hygiene treatment", "hygiene")),
    "water_heater": (
        ("Prepare the water service for a 40-degree shower request.", "a 40-degree water-service request", "water40"),
        ("Prepare the water service for a 60-degree cleaning request.", "a 60-degree water-service request", "water60")),
    "oven": (
        ("Bake the cake using the enclosed convection programme.", "convection baking", "baking"),
        ("Grill the food using the upper radiant programme.", "upper radiant grilling", "grilling")),
}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def prepare():
    parent_manifest, sources = load_locked()
    files = {}
    for profile in PROFILES:
        parent = profile[:2]
        variant = 0 if profile.endswith("A") else 1
        for pressure in PRESSURES:
            episode = deepcopy(sources[parent, pressure])
            episode["episode_id"] = f"HC-CHOICE-{profile}-{pressure:g}"
            episode["base_episode_id"] = f"HC-CHOICE-{profile}"
            episode["source_type"] = "controlled_paired_action_choice"
            episode["review_status"] = "unreviewed_controlled_service_contract"
            episode["action_grounding"] = []
            episode["tool_catalog"] = []
            episode["goals"] = []
            episode["home"]["resources"]["task_power_bounds_kw"] = {}
            episode["initial_state"]["values"]["services"] = {}
            for index, task in enumerate(episode["task_stream"]):
                device = task["action_template"]["target"]
                task["task_id"] = f"task{index + 1:02}"
                options = MODES[device]
                selected = variant
                task["goal"] = (options[selected][0] +
                                f" Complete the requested service within {task['completion_deadline_ms'] // 60000} minutes.")
                op = f"preset_{selected + 1}"
                task["required_action"]["operation"] = op
                task["action_template"]["operation"] = op
                agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
                agent["role"] = f"Operate the {device} service interface."
                agent["observable_state"] = [f"devices.{device}", f"services.{device}"]
                agent["tools"] = [f"{device}_preset_1", f"{device}_preset_2", f"{device}_off"]
                episode["initial_state"]["values"]["services"][device] = "none"
                episode["goals"].append({"path": f"services.{device}", "op": "eq", "value": options[selected][2]})
                template = task["action_template"]
                power, duration = template["power_kw"], template["duration_ms"]
                episode["home"]["resources"]["task_power_bounds_kw"][task["task_id"]] = power
                tools = []
                for mode_index, (_, description, service) in enumerate(options):
                    operation = f"preset_{mode_index + 1}"
                    effects = {f"devices.{device}": "complete", f"services.{device}": service}
                    tools.append({
                        "agent_id": agent["agent_id"], "tool_name": f"{device}_{operation}",
                        "target": device, "operation": operation, "parameters": [],
                        "preconditions": deepcopy(template["requires"]),
                        "description": f"Provide {description}. Controlled cycle: {duration} ms, {power} kW. These costs are scenario settings.",
                    })
                    episode["action_grounding"].append({
                        "agent_id": agent["agent_id"], "task_id": task["task_id"],
                        "target": device, "operation": operation, "grounded_operation": operation,
                        "start_effects": {f"devices.{device}": "running"},
                        "completion_effects": effects, "effects": effects,
                        "duration_ms": duration, "power_kw": power,
                    })
                tools.append({"agent_id": agent["agent_id"], "tool_name": f"{device}_off",
                              "target": device, "operation": "off", "parameters": [],
                              "preconditions": deepcopy(template["requires"]),
                              "description": "Leave this device idle; provide no requested service. Cost: 100 ms, 0 kW."})
                episode["action_grounding"].append({
                    "agent_id": agent["agent_id"], "task_id": task["task_id"], "target": device,
                    "operation": "off", "grounded_operation": "off",
                    "effects": {f"devices.{device}": "idle", f"services.{device}": "none"},
                    "duration_ms": 100, "power_kw": 0.0,
                })
                # The catalogue order is identical within each A/B pair.
                random.Random(f"20260930:{parent}:{device}").shuffle(tools)
                episode["tool_catalog"].extend(tools)
            episode["scenario_assumptions"].update({
                "service_semantics": "declared categorical service contract; no thermal or hygiene physics",
                "equal_preset_costs": "intentional controlled abstraction to isolate action-choice errors",
                "mode_effects_independent_of_requested_mode": True,
            })
            path = DIR / f"{profile}-{pressure:g}.json"
            write(path, episode)
            files[path.name] = digest(path)
    manifest = {
        "version": "c3-action-choice-0.1", "candidate_sha256": files,
        "parent_candidate_sha256": parent_manifest["candidate_sha256"],
        "profiles": list(PROFILES), "independent_scheduling_structures": 2,
        "pressures": list(PRESSURES), "policies": list(POLICIES),
        "offline_cells": 4 * 3 * 6 * 5,
        "negative_controls": "one wrong preset or off for each task, every policy, only rho=0.8",
        "negative_control_cells": 4 * 3 * 2 * 5,
        "live_profiles": list(PROFILES), "live_repetitions": 1,
        "live_agent_requests_planned": 12, "live_replay_cells_if_complete": 60,
        "status": "locked_before_feasibility_and_policy_results",
    }
    write(DIR / "manifest.json", manifest)
    return manifest


def load():
    manifest = json.loads((DIR / "manifest.json").read_text(encoding="utf8"))
    episodes = {}
    for profile in PROFILES:
        for pressure in PRESSURES:
            path = DIR / f"{profile}-{pressure:g}.json"
            if digest(path) != manifest["candidate_sha256"][path.name]:
                raise ValueError("locked input changed: " + str(path))
            episodes[profile, pressure] = json.loads(path.read_text(encoding="utf8"))
    return manifest, episodes


def public_episode(episode, profile):
    sample = deepcopy(episode)
    sample["episode_id"] = "HC-PUBLIC-" + PUBLIC[profile]
    sample["base_episode_id"] = sample["episode_id"]
    return sample


def preflight():
    manifest, episodes = load()
    rows = []
    requests_by_profile = {}
    for (profile, pressure), episode in episodes.items():
        sample = public_episode(episode, profile)
        requests = []
        for task in sample["task_stream"]:
            agent = next(a for a in sample["agents"] if a["agent_id"] == task["agent_id"])
            request = build_agent_request(sample, agent, task, architecture="IndependentMultiAgent",
                                          current_time_ms=0, request_id=f"{sample['base_episode_id']}:{task['task_id']}")
            text = json.dumps(request, ensure_ascii=False)
            if (request["goals"] or request["constraints"] or len(request["available_actions"]) != 3
                    or any(s in text for s in ("required_action", "action_template", "max_power_kw", "RHO", "load_to_capacity_ratio"))
                    or any(t["task_id"] in text for t in sample["task_stream"] if t != task)):
                raise ValueError("request audit failed")
            requests.append(request)
        requests_by_profile.setdefault(profile, requests)
        # Changing resource pressure must not change the actual specialist input.
        if requests_by_profile[profile] != requests:
            raise ValueError("capacity leaked into specialist input")
        rows.append({"profile": profile, "pressure": pressure,
                     "oracle_schedule": ideal_schedule(episode), "requests_audited": len(requests)})
    for parent in ("P1", "P2"):
        for a, b in zip(requests_by_profile[parent + "A"], requests_by_profile[parent + "B"]):
            if a["available_actions"] != b["available_actions"]:
                raise ValueError("catalogue changed between demand profiles")
    result = {"manifest_sha256": digest(DIR / "manifest.json"), "rows": rows,
              "feasible_cells": sum(x["oracle_schedule"] is not None for x in rows),
              "requests_by_profile": requests_by_profile}
    write(DIR / "preflight.json", result)
    return result


def summarize(rows):
    result = {}
    for profile in PROFILES:
        result[profile] = {}
        for pressure in PRESSURES:
            result[profile][str(pressure)] = {}
            for policy in POLICIES:
                selected = [r for r in rows if r["profile"] == profile and r["pressure"] == pressure and r["policy"] == policy]
                times = [r["first_safe_action_ms"] for r in selected if r["first_safe_action_ms"] is not None]
                result[profile][str(pressure)][policy] = {
                    "runs": len(selected), "all_tasks_served": sum(r["all_tasks_served"] for r in selected),
                    "all_deadlines_met": sum(r["all_deadlines_met"] for r in selected),
                    "final_goal_success": sum(r["final_goal_success"] for r in selected),
                    "median_first_safe_action_ms": median(times) if times else None,
                }
    return result


def simulate(episode, client, profile, pressure, policy):
    trace, result = run_event_simulation(deepcopy(episode), client, policy,
                                        "controlled paired action-choice replay", shared_safety_gate=True)
    return {"profile": profile, "pressure": pressure, "policy": policy,
            "all_tasks_served": all(result["task_service"].values()),
            "all_deadlines_met": result["all_deadlines_met"],
            "task_service": result["task_service"], "task_deadline_met": result["task_deadline_met"],
            "final_goal_success": result["final_goal_success"],
            "first_safe_action_ms": result["first_action_start_latency_ms"],
            "first_goal_progress_ms": result["first_goal_progress_latency_ms"],
            "shared_gate_rejections": result["shared_safety_gate_rejection_count"],
            "start_order": [e["task_id"] for e in trace["events"] if e["type"] == "action_started"]}


class ErrorClient(ScriptedProposalClient):
    def __init__(self, latencies, task_id, error):
        super().__init__(latencies)
        self.task_id, self.error = task_id, error

    def decide(self, request, instructions=""):
        decision = super().decide(request, instructions)
        if request["task"]["task_id"] == self.task_id:
            action = decision["actions"][0]
            action["operation"] = ("off" if self.error == "off" else
                                   "preset_2" if action["operation"] == "preset_1" else "preset_1")
            if self.error == "off":
                action["estimated_duration_ms"], action["estimated_power_kw"] = 100, 0.0
        return decision


def offline():
    manifest, episodes = load()
    pre = preflight()
    rows, negatives = [], []
    for profile in PROFILES:
        ids = tuple(t["task_id"] for t in episodes[profile, 0.8]["task_stream"])
        for order in itertools.permutations(ids):
            latencies = latencies_for_order(order)
            for pressure in PRESSURES:
                for policy in POLICIES:
                    row = simulate(episodes[profile, pressure], ScriptedProposalClient(latencies), profile, pressure, policy)
                    row["arrival_order"] = list(order)
                    rows.append(row)
        for task_id in ids:
            for error in ("wrong_preset", "off"):
                for policy in POLICIES:
                    row = simulate(episodes[profile, 0.8], ErrorClient(latencies_for_order(ids), task_id, error), profile, 0.8, policy)
                    row.update({"injected_task": task_id, "injected_error": error})
                    negatives.append(row)
    payload = {"manifest_sha256": digest(DIR / "manifest.json"), "api_calls": 0,
               "status": "controlled_synthetic_semantic_and_scheduling_probe",
               "preflight_feasible_cells": pre["feasible_cells"],
               "rows": rows, "summary": summarize(rows), "negative_controls": negatives}
    write(OFFLINE, payload)
    return payload


def live():
    manifest, episodes = load()
    preflight()
    manifest_hash = digest(DIR / "manifest.json")
    if LIVE.exists():
        payload = json.loads(LIVE.read_text(encoding="utf8"))
        if payload["manifest_sha256"] != manifest_hash:
            raise ValueError("live result belongs to another input batch")
    else:
        payload = {"manifest_sha256": manifest_hash, "model": "deepseek-flash",
                   "requests_planned": 12, "repetitions_per_profile": 1,
                   "status": "controlled_semantic_choice_pilot", "batches": []}
    LOGDIR.mkdir(parents=True, exist_ok=True)
    client = DeepSeekResponsesClient(model="deepseek-flash", max_attempts=2,
                                    logger=EventLogger(LOGDIR / "model_events.jsonl", "c3-action-choice-20260930"))
    for profile in PROFILES:
        if any(b["profile"] == profile for b in payload["batches"]):
            continue  # Preserve model failures, no selective replacement.
        sample = sample_parallel(client, public_episode(episodes[profile, 1.2], profile), 1)
        scores = []
        for task in episodes[profile, 1.2]["task_stream"]:
            record = sample["records"].get(task["task_id"])
            actions = record["decision"]["actions"] if record else []
            authorized = len(actions) == 1 and validate_tool_call(episodes[profile, 1.2], task["agent_id"], task["task_id"], actions[0]) is None
            correct = authorized and all(actions[0].get(k) == v for k, v in task["required_action"].items())
            scores.append({"task_id": task["task_id"], "authorized": authorized,
                           "semantic_correct": correct, "operation": actions[0]["operation"] if actions else None})
        payload["batches"].append({"profile": profile, "sample": sample, "proposal_scores": scores})
        write(LIVE, payload)
        print(json.dumps({"profile": profile, "errors": sample["errors"], "scores": scores}, ensure_ascii=False), flush=True)
    rows = []
    for batch in payload["batches"]:
        profile = batch["profile"]
        records = batch["sample"]["records"]
        if batch["sample"]["errors"]:
            continue
        for pressure in PRESSURES:
            episode = episodes[profile, pressure]
            ordered = [records[t["task_id"]] for t in episode["task_stream"]]
            for policy in POLICIES:
                replay = MemoryReplayClient(deepcopy(ordered))
                rows.append(simulate(episode, replay, profile, pressure, policy))
                replay.assert_consumed()
    payload["replays"], payload["summary"] = rows, summarize(rows)
    write(LIVE, payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "preflight", "offline", "live"))
    args = parser.parse_args()
    data = {"prepare": prepare, "preflight": preflight, "offline": offline, "live": live}[args.stage]()
    negative_count = (len(data["negative_controls"]) if isinstance(data.get("negative_controls"), list)
                      else data.get("negative_control_cells", 0))
    print(json.dumps({"stage": args.stage, "profiles": data.get("profiles"),
                      "feasible_cells": data.get("feasible_cells", data.get("preflight_feasible_cells")),
                      "rows": len(data.get("rows", data.get("replays", []))),
                      "negative_controls": negative_count}, ensure_ascii=False))
