"""Fixed scale/release/deadline grid; exact feasibility is analysis-only.

Six author-generated structures, two at each agent count. All generated cells
are retained, including intrinsically impossible budgets or deadlines.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from copy import deepcopy

from probe_c3_action_choice_20260930 import MODES, POLICIES, write, digest, simulate
from probe_c3_parallel_model_pilot import sample_parallel
from probe_c3_prospective_candidates_20260930 import POOL
from probe_c3_structural_generalization import ScriptedProposalClient, make_episode_from_specs
from probe_c3_staggered_release import release_order_records
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.protocol import build_agent_request
from runtime.replay_client import MemoryReplayClient
from runtime.scheduling_oracle import ideal_schedule
from runtime.tool_contract import validate_tool_call
from runtime.event_simulator import run_event_simulation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "revision_drafts" / "20260930_c3_scale_release"
OFFLINE = ROOT / "results" / "c3_scale_release_offline_20260930.json"
LIVE = ROOT / "results" / "c3_scale_release_model_20260930.json"
LOGDIR = ROOT / "runs" / "c3-scale-release-20260930"
SEED = 2026093002
COUNTS = (2, 4, 5)
PRESSURES = (0.8, 1.2, 1.6)
RELEASES = ("together", "urgent_late", "urgent_first")
DEADLINES = ("tight", "loose")
MINUTE = 60000
OPTIONS = dict(MODES, **{
    "kettle": (("Prepare water for tea that requires a freshly boiled service.", "freshly boiled water service", "boiled"),
               ("Keep the already prepared water ready with a warming service.", "water warming service without a new boil", "kept_warm")),
    "cooktop": (("Cook the uncooked meal; a reheating-only service will not suffice.", "full cooking service for uncooked food", "cooked"),
                ("Reheat the meal that has already been cooked.", "reheating service for cooked food", "reheated")),
    "washer": (("Clean the ordinary cotton laundry with an everyday service.", "ordinary cotton washing", "cotton"),
               ("Clean the delicate laundry with the fabric-care service.", "delicate fabric-care washing", "delicate")),
    "ev_charger": (("Provide an ordinary charging session for the vehicle.", "ordinary vehicle charging service", "charged"),
                   ("Provide the vehicle's battery-conditioning service.", "battery-conditioning service", "conditioned")),
})


def templates():
    rng = random.Random(SEED)
    return {f"N{count}-{index}": tuple(POOL[name] for name in rng.sample(tuple(POOL), count))
            for count in COUNTS for index in (1, 2)}


def public_id(template):
    return "HC-PUBLIC-" + dict(zip(templates(), ("A19", "F37", "L82", "R46", "U53", "Y28")))[template]


def key(template, deadline, release, pressure):
    return f"{template}-{deadline}-{release}-{pressure:g}.json"


def build(template, specs, deadline, release, pressure):
    episode = make_episode_from_specs(template, specs, pressure)
    episode["episode_id"] = "HC-SCALE-" + key(template, deadline, release, pressure)[:-5]
    episode["base_episode_id"] = public_id(template)
    episode["source_type"] = "controlled_scale_release_deadline_candidate"
    episode["review_status"] = "author_only_not_frozen"
    episode["simulation"]["blind_future_task_arrivals"] = True
    episode["action_grounding"], episode["tool_catalog"], episode["goals"] = [], [], []
    episode["initial_state"]["values"]["services"] = {}
    episode["home"]["resources"]["task_power_bounds_kw"] = {}
    urgent_index = min(range(len(specs)), key=lambda i: (specs[i].deadline_min, i))
    total_duration = sum(s.duration_min for s in specs)
    for i, (task, spec) in enumerate(zip(episode["task_stream"], specs)):
        device = spec.device
        task["task_id"] = f"task{i + 1:02}"
        offset = (MINUTE if (release == "urgent_late" and i == urgent_index)
                  or (release == "urgent_first" and i != urgent_index) else 0)
        window_min = spec.deadline_min if deadline == "tight" else spec.duration_min + total_duration + 10
        task["release_at_ms"] = offset
        task["completion_deadline_ms"] = offset + window_min * MINUTE
        selected = random.Random(f"{SEED}:{template}:{device}").randrange(2)
        choices = OPTIONS[device]
        task["goal"] = choices[selected][0] + f" Finish within {window_min} minutes after this request arrives."
        op = f"preset_{selected + 1}"
        task["required_action"]["operation"] = op
        task["action_template"]["operation"] = op
        agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
        agent["role"] = f"Operate the {device} service interface."
        agent["observable_state"] = [f"devices.{device}", f"services.{device}"]
        agent["tools"] = [f"{device}_preset_1", f"{device}_preset_2", f"{device}_off"]
        episode["initial_state"]["values"]["services"][device] = "none"
        episode["goals"].append({"path": f"services.{device}", "op": "eq", "value": choices[selected][2]})
        episode["home"]["resources"]["task_power_bounds_kw"][task["task_id"]] = spec.power_kw
        catalog = []
        for mode_index, (_, description, service) in enumerate(choices):
            operation = f"preset_{mode_index + 1}"
            effects = {f"devices.{device}": "complete", f"services.{device}": service}
            catalog.append({"agent_id": spec.agent_id, "tool_name": f"{device}_{operation}",
                            "target": device, "operation": operation, "parameters": [],
                            "preconditions": deepcopy(task["action_template"]["requires"]),
                            "description": f"Provide {description}. Controlled costs: {spec.duration_min * MINUTE} ms, {spec.power_kw} kW."})
            episode["action_grounding"].append({
                "agent_id": spec.agent_id, "task_id": task["task_id"], "target": device,
                "operation": operation, "grounded_operation": operation,
                "duration_ms": spec.duration_min * MINUTE, "power_kw": spec.power_kw,
                "start_effects": {f"devices.{device}": "running"},
                "completion_effects": effects, "effects": effects,
            })
        catalog.append({"agent_id": spec.agent_id, "tool_name": f"{device}_off", "target": device,
                        "operation": "off", "parameters": [],
                        "preconditions": deepcopy(task["action_template"]["requires"]),
                        "description": "Leave the device idle and provide no service. Cost: 100 ms, 0 kW."})
        episode["action_grounding"].append({
            "agent_id": spec.agent_id, "task_id": task["task_id"], "target": device,
            "operation": "off", "grounded_operation": "off", "duration_ms": 100, "power_kw": 0.0,
            "effects": {f"devices.{device}": "idle", f"services.{device}": "none"},
        })
        random.Random(f"{SEED}:{template}:{device}:tools").shuffle(catalog)
        episode["tool_catalog"].extend(catalog)
    episode["scenario_assumptions"].update({
        "release_delay_ms": MINUTE,
        "deadline_semantics": "window relative to each task's release; late tasks retain their own window",
        "service_semantics": "controlled categorical service contracts; equal preset costs; no calibrated physics",
        "cross_task_dependencies": "none; independent requests",
        "policy_information": "released task metadata and public bounds only; future release events hidden",
    })
    episode["design_factors"] = {"template": template, "agent_count": len(specs),
                                 "deadline": deadline, "release": release, "pressure": pressure}
    return episode


def prepare():
    files = {}
    for template, specs in templates().items():
        for deadline, release, pressure in itertools.product(DEADLINES, RELEASES, PRESSURES):
            path = DIR / key(template, deadline, release, pressure)
            write(path, build(template, specs, deadline, release, pressure))
            files[path.name] = digest(path)
    manifest = {
        "version": "c3-scale-release-0.1", "seed": SEED,
        "pool_order": list(POOL), "pool_controlled_specs": {k: vars(v) for k, v in POOL.items()},
        "templates": {t: [s.device for s in specs] for t, specs in templates().items()},
        "deadlines": list(DEADLINES), "releases": list(RELEASES), "pressures": list(PRESSURES),
        "policies": list(POLICIES), "candidate_sha256": files,
        "offline_cells": 2 * (2 + 24 + 120) * 2 * 3 * 3 * 5,
        "arrival_order_design": "all permutations; each task response duration 800 + 200 * rank ms",
        "api_sample_templates": ["N2-1", "N4-1", "N5-1"],
        "api_sample_condition": "tight/together/1.2, one concurrent batch per selected template",
        "api_requests_planned": 11, "recorded_proposal_counterfactual_cells": 270,
        "status": "locked_before_feasibility_and_policy_replay",
        "analysis_units": "six controlled structures; interventions and permutations are dependent",
        "agent_count_comparison": "device composition differs; not a causal agent-count-only comparison",
    }
    write(DIR / "manifest.json", manifest)
    return manifest


def load():
    manifest = json.loads((DIR / "manifest.json").read_text(encoding="utf8"))
    episodes = {}
    for filename, expected in manifest["candidate_sha256"].items():
        path = DIR / filename
        if digest(path) != expected:
            raise ValueError("locked candidate changed: " + filename)
        episode = json.loads(path.read_text(encoding="utf8"))
        f = episode["design_factors"]
        episodes[f["template"], f["deadline"], f["release"], f["pressure"]] = episode
    return manifest, episodes


def checked_schedule(episode):
    schedule = ideal_schedule(episode)
    if schedule is None:
        return None
    tasks = {t["task_id"]: t for t in episode["task_stream"]}
    if {s["task_id"] for s in schedule} != set(tasks):
        raise ValueError("oracle omitted a task")
    for row in schedule:
        task = tasks[row["task_id"]]
        if (row["start_ms"] < task["release_at_ms"]
                or row["finish_ms"] > task["completion_deadline_ms"]
                or row["finish_ms"] - row["start_ms"] != task["action_template"]["duration_ms"]):
            raise ValueError("oracle schedule violates clock contract")
    cap = episode["home"]["resources"]["max_power_kw"]
    for at in {r["start_ms"] for r in schedule}:
        load_kw = sum(tasks[r["task_id"]]["action_template"]["power_kw"] for r in schedule
                      if r["start_ms"] <= at < r["finish_ms"])
        if load_kw > cap + 1e-9:
            raise ValueError("oracle schedule exceeds capacity")
    return schedule


def preflight():
    _, episodes = load()
    rows = []
    for factors, episode in episodes.items():
        tasks = episode["task_stream"]
        # At each task release, specialist receives only its own task/state.
        for task in tasks:
            agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
            released = {t["task_id"] for t in tasks if t["release_at_ms"] <= task["release_at_ms"]}
            request = build_agent_request(episode, agent, task, architecture="IndependentMultiAgent",
                                          current_time_ms=task["release_at_ms"], released_task_ids=released,
                                          request_id=f"{episode['base_episode_id']}:{task['task_id']}")
            text = json.dumps(request)
            if (request["goals"] or request["constraints"] or len(request["available_actions"]) != 3
                    or any(x in text for x in ("max_power_kw", "required_action", "action_template", "design_factors", "RHO", "urgent_late", "urgent_first"))
                    or any(t["task_id"] in text for t in tasks if t["task_id"] != task["task_id"])
                    or request["episode_id"] != episode["base_episode_id"]):
                raise ValueError("specialist information audit failed")
        schedule = checked_schedule(episode)
        rows.append({**episode["design_factors"], "oracle_feasible": schedule is not None,
                     "oracle_schedule": schedule, "requests_audited": len(tasks)})
    payload = {"manifest_sha256": digest(DIR / "manifest.json"), "rows": rows,
               "feasible_cells": sum(r["oracle_feasible"] for r in rows)}
    write(DIR / "preflight.json", payload)
    return payload


def aggregate(rows):
    groups = {}
    for row in rows:
        group = "|".join(str(row[x]) for x in ("template", "deadline", "release", "pressure", "policy"))
        cell = groups.setdefault(group, {k: row[k] for k in ("template", "agent_count", "deadline", "release", "pressure", "policy", "oracle_feasible")})
        cell.setdefault("runs", 0)
        cell["runs"] += 1
        for metric in ("all_tasks_served", "all_deadlines_met", "final_goal_success"):
            cell[metric] = cell.get(metric, 0) + int(bool(row[metric]))
        cell.setdefault("first_action_count", 0)
        cell.setdefault("first_action_sum_ms", 0)
        if row["first_safe_action_ms"] is not None:
            cell["first_action_count"] += 1
            cell["first_action_sum_ms"] += row["first_safe_action_ms"]
    for cell in groups.values():
        total = cell.pop("first_action_sum_ms")
        cell["mean_first_safe_action_ms"] = total / cell["first_action_count"] if cell["first_action_count"] else None
    return list(groups.values())


def offline():
    manifest, episodes = load()
    pre = preflight()
    feasible = {(r["template"], r["deadline"], r["release"], r["pressure"]): r["oracle_feasible"] for r in pre["rows"]}
    rows = []
    for template, specs in templates().items():
        ids = tuple(f"task{i + 1:02}" for i in range(len(specs)))
        for order in itertools.permutations(ids):
            latencies = {task_id: 800 + rank * 200 for rank, task_id in enumerate(order)}
            for deadline, release, pressure in itertools.product(DEADLINES, RELEASES, PRESSURES):
                episode = episodes[template, deadline, release, pressure]
                for policy in POLICIES:
                    row = simulate(episode, ScriptedProposalClient(latencies), template, pressure, policy)
                    row.update(episode["design_factors"])
                    row.update({"arrival_rank": list(order), "oracle_feasible": feasible[template, deadline, release, pressure]})
                    rows.append(row)
        print(json.dumps({"template_completed": template, "rows_so_far": len(rows)}), flush=True)
    if len(rows) != manifest["offline_cells"]:
        raise ValueError("incomplete predetermined grid")
    result = {"manifest_sha256": digest(DIR / "manifest.json"), "api_calls": 0,
              "status": "controlled_scale_release_deadline_grid", "rows": rows,
              "summary": aggregate(rows), "preflight_feasible_cells": pre["feasible_cells"]}
    write(OFFLINE, result)
    return result


def live():
    manifest, episodes = load()
    pre = preflight()
    feasible = {(r["template"], r["deadline"], r["release"], r["pressure"]): r["oracle_feasible"] for r in pre["rows"]}
    manifest_hash = digest(DIR / "manifest.json")
    if LIVE.exists():
        result = json.loads(LIVE.read_text(encoding="utf8"))
        if result["manifest_sha256"] != manifest_hash:
            raise ValueError("existing live batch uses different candidates")
    else:
        result = {"manifest_sha256": manifest_hash, "model": "deepseek-flash", "batches": [],
                  "requests_planned": manifest["api_requests_planned"],
                  "status": "canonical_concurrent_proposals_plus_counterfactual_replay",
                  "sampling_condition": manifest["api_sample_condition"]}
    LOGDIR.mkdir(parents=True, exist_ok=True)
    client = DeepSeekResponsesClient(model="deepseek-flash", max_attempts=2,
                                    logger=EventLogger(LOGDIR / "model_events.jsonl", "c3-scale-release-20260930"))
    for template in manifest["api_sample_templates"]:
        if any(b["template"] == template for b in result["batches"]):
            continue
        sample_episode = deepcopy(episodes[template, "tight", "together", 1.2])
        # All tasks are released together at sampling; there are no future tasks.
        # Local visibility and public aliases retain the same blind input fields.
        sample_episode["episode_id"] = sample_episode["base_episode_id"]
        sample_episode["simulation"].pop("blind_future_task_arrivals")
        sample = sample_parallel(client, sample_episode, 1)
        scores = []
        for task in sample_episode["task_stream"]:
            record = sample["records"].get(task["task_id"])
            actions = record["decision"]["actions"] if record else []
            authorized = len(actions) == 1 and validate_tool_call(sample_episode, task["agent_id"], task["task_id"], actions[0]) is None
            correct = authorized and all(actions[0].get(k) == v for k, v in task["required_action"].items())
            scores.append({"task_id": task["task_id"], "authorized": authorized, "semantic_correct": correct})
        result["batches"].append({"template": template, "sample": sample, "proposal_scores": scores})
        write(LIVE, result)
        print(json.dumps({"template": template, "errors": sample["errors"], "proposal_scores": scores}), flush=True)
    rows = []
    for batch in result["batches"]:
        if batch["sample"]["errors"]:
            continue
        template, records = batch["template"], batch["sample"]["records"]
        for deadline, release, pressure in itertools.product(DEADLINES, RELEASES, PRESSURES):
            episode = episodes[template, deadline, release, pressure]
            for policy in POLICIES:
                replay = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
                row = simulate(episode, replay, template, pressure, policy)
                replay.assert_consumed()
                row.update(episode["design_factors"])
                row["oracle_feasible"] = feasible[template, deadline, release, pressure]
                rows.append(row)
    result["replays"], result["summary"] = rows, aggregate(rows)
    write(LIVE, result)
    return result


def audit_commits():
    """Post-hoc mechanism audit, not a new confirmatory test or model run."""
    manifest, episodes = load()
    rows = []
    for template in manifest["api_sample_templates"]:
        episode = episodes[template, "tight", "urgent_late", 1.6]
        ids = [t["task_id"] for t in episode["task_stream"]]
        latencies = {task_id: 800 + rank * 200 for rank, task_id in enumerate(ids)}
        trace, result = run_event_simulation(episode, ScriptedProposalClient(latencies),
                                            "DeadlineAwareCoordinator", "post-hoc early-commit diagnostic",
                                            shared_safety_gate=True)
        late_at = max(t["release_at_ms"] for t in episode["task_stream"])
        fixed = {e["task_id"]: e["timestamp_ms"] for e in trace["events"]
                 if e["type"] == "action_started" and e["timestamp_ms"] < late_at}
        remaining_schedule = ideal_schedule(episode, now_ms=late_at, forced_starts=fixed)
        rows.append({"template": template, "late_task_release_ms": late_at,
                     "committed_starts_before_release": fixed,
                     "all_deadlines_met_by_policy": result["all_deadlines_met"],
                     "oracle_schedule_without_prior_commits": checked_schedule(episode),
                     "oracle_feasible_after_actual_commits": remaining_schedule is not None,
                     "oracle_schedule_after_actual_commits": remaining_schedule})
    payload = {"status": "post_hoc_canonical_rank_mechanism_diagnostic",
               "api_calls": 0, "manifest_sha256": digest(DIR / "manifest.json"), "rows": rows,
               "limitations": "Known-future oracle diagnoses loss of feasibility; it is not an online baseline."}
    write(ROOT / "results" / "c3_scale_release_commit_audit_20260930.json", payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "preflight", "offline", "live", "audit"))
    args = parser.parse_args()
    data = {"prepare": prepare, "preflight": preflight, "offline": offline, "live": live, "audit": audit_commits}[args.stage]()
    print(json.dumps({"stage": args.stage, "templates": data.get("templates"),
                      "cells": len(data.get("rows", data.get("replays", []))),
                      "feasible_cells": data.get("feasible_cells", data.get("preflight_feasible_cells")),
                      "planned_offline_cells": data.get("offline_cells")}, ensure_ascii=False))
