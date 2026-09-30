"""Same locked grid, stronger released-only admission and explicit foresight.

Public cost contracts are parsed from advertised tool descriptions. The
perfect-announcement arm intentionally has extra information and is an upper
information diagnostic, not a fair same-information winner or new algorithm.
"""
import argparse
import itertools
import json
import re
from copy import deepcopy
from time import perf_counter

from probe_c3_action_choice_20260930 import write, digest
from probe_c3_scale_release_20260930 import (
    ROOT, DIR as SOURCE_DIR, load, templates, PRESSURES, DEADLINES, RELEASES,
    aggregate, checked_schedule,
)
from probe_c3_structural_generalization import ScriptedProposalClient
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient

DIR = ROOT / "revision_drafts" / "20260930_c3_information_baselines"
OUTPUT = ROOT / "results" / "c3_information_baselines_20260930.json"
SOURCE_MODEL = ROOT / "results" / "c3_scale_release_model_20260930.json"
NEW_POLICIES = ("ReleasedFeasibilityStrict", "ReleasedFeasibilityFallback", "PerfectAnnouncementReserve")


def contracts(episode):
    result = {}
    for task in episode["task_stream"]:
        tools = [x for x in episode["tool_catalog"] if x["agent_id"] == task["agent_id"] and x["operation"] != "off"]
        costs = []
        for tool in tools:
            match = re.search(r"Controlled costs: (\d+) ms, ([\d.]+) kW\.", tool["description"])
            if not match:
                raise ValueError("no published cost contract")
            costs.append((int(match.group(1)), float(match.group(2))))
        if len(costs) != 2 or costs[0] != costs[1]:
            raise ValueError("this admission experiment requires equal advertised preset costs")
        if costs[0][1] != episode["home"]["resources"]["task_power_bounds_kw"][task["task_id"]]:
            raise ValueError("advertised cost and public bound disagree")
        result[task["task_id"]] = {"duration_ms": costs[0][0], "power_kw": costs[0][1]}
    return result


def adapt(episode, label):
    changed = deepcopy(episode)
    public = contracts(episode)
    for task in changed["task_stream"]:
        task["action_template"].update(public[task["task_id"]])
    changed["published_service_costs"] = public
    if label == "PerfectAnnouncementReserve":
        late = [t for t in changed["task_stream"] if t["release_at_ms"] > 0]
        if changed["design_factors"]["release"] != "urgent_late" or len(late) != 1:
            raise ValueError("announcement arm is defined only for one future urgent request")
        task = late[0]
        changed["simulation"]["potential_urgent"] = {
            "task_id": task["task_id"], **public[task["task_id"]],
            "deadline_ms": task["completion_deadline_ms"],
            "possible_release_ms": [task["release_at_ms"]],
            "interpretation": "perfect disclosed future request; privileged diagnostic",
        }
        policy = "RobustReserveCoordinator"
    else:
        changed["simulation"].pop("potential_urgent", None)
        changed["simulation"]["observed_feasibility_fallback"] = label == "ReleasedFeasibilityFallback"
        policy = "ObservedTaskFeasibilityCoordinator"
    return changed, policy


def prepare():
    manifest, episodes = load()
    public = {filename: contracts(episode) for filename, episode in
              (("|".join(map(str, f)), e) for f, e in episodes.items())}
    result = {
        "version": "c3-information-baselines-0.1",
        "source_manifest_sha256": digest(SOURCE_DIR / "manifest.json"),
        "source_candidate_sha256": manifest["candidate_sha256"],
        "source_model_sha256": digest(SOURCE_MODEL),
        "public_cost_contracts": public,
        "released_only_policies": list(NEW_POLICIES[:2]),
        "announcement_policy": NEW_POLICIES[2],
        "announcement_cells": "urgent_late only; exact future class and release disclosed",
        "offline_new_cells": 5256 * 2 + 1752,
        "recorded_new_cells": 54 * 2 + 18,
        "new_api_calls": 0,
        "execution_capabilities": "all arms noninterruptible cycles; identical shared safety gate",
        "same_information": "strict/fallback use released metadata plus advertised constant costs; announcement has extra future information",
        "timing": "solver simulation wall time logged separately; not added to virtual first-action time",
        "status": "locked_before_new_baseline_results",
    }
    write(DIR / "manifest.json", result)
    return result


def locked():
    design = json.loads((DIR / "manifest.json").read_text(encoding="utf8"))
    source, episodes = load()
    if (design["source_manifest_sha256"] != digest(SOURCE_DIR / "manifest.json")
            or design["source_candidate_sha256"] != source["candidate_sha256"]
            or design["source_model_sha256"] != digest(SOURCE_MODEL)):
        raise ValueError("source changed since stronger-baseline design lock")
    return design, episodes


def run_one(episode, label, client):
    changed, runtime_policy = adapt(episode, label)
    start = perf_counter()
    trace, result = run_event_simulation(changed, client, runtime_policy,
                                         "public contract stronger baseline replay", shared_safety_gate=True)
    elapsed = (perf_counter() - start) * 1000
    f = episode["design_factors"]
    return {**f, "policy": label,
            "oracle_feasible": True,  # Rechecked for every locked source in run().
            "all_tasks_served": all(result["task_service"].values()),
            "all_deadlines_met": result["all_deadlines_met"],
            "final_goal_success": result["final_goal_success"],
            "task_service": result["task_service"], "task_deadline_met": result["task_deadline_met"],
            "first_safe_action_ms": result["first_action_start_latency_ms"],
            "simulation_wall_ms": elapsed,
            "fallback_count": sum(e["type"] == "feasibility_fallback" for e in trace["events"]),
            "viability_defer_count": sum(e["type"] == "coordination_decision" and e.get("decision") == "defer" for e in trace["events"]),
            "start_order": [e["task_id"] for e in trace["events"] if e["type"] == "action_started"]}


def run():
    design, episodes = locked()
    for episode in episodes.values():
        if checked_schedule(episode) is None:
            raise ValueError("source claimed feasible but no oracle schedule exists")
    rows = []
    for template, specs in templates().items():
        ids = tuple(f"task{i + 1:02}" for i in range(len(specs)))
        for order in itertools.permutations(ids):
            latencies = {task_id: 800 + rank * 200 for rank, task_id in enumerate(order)}
            for deadline, release, pressure in itertools.product(DEADLINES, RELEASES, PRESSURES):
                episode = episodes[template, deadline, release, pressure]
                labels = NEW_POLICIES if release == "urgent_late" else NEW_POLICIES[:2]
                for label in labels:
                    row = run_one(episode, label, ScriptedProposalClient(latencies))
                    row["arrival_rank"] = list(order)
                    rows.append(row)
        print(json.dumps({"template_completed": template, "new_rows": len(rows)}), flush=True)
    saved = json.loads(SOURCE_MODEL.read_text(encoding="utf8"))
    recorded = []
    for batch in saved["batches"]:
        if batch["sample"]["errors"]:
            continue
        template, records = batch["template"], batch["sample"]["records"]
        for deadline, release, pressure in itertools.product(DEADLINES, RELEASES, PRESSURES):
            episode = episodes[template, deadline, release, pressure]
            labels = NEW_POLICIES if release == "urgent_late" else NEW_POLICIES[:2]
            for label in labels:
                client = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
                recorded.append(run_one(episode, label, client))
                client.assert_consumed()
    if len(rows) != design["offline_new_cells"] or len(recorded) != design["recorded_new_cells"]:
        raise ValueError("incomplete predetermined new baseline grid")
    result = {"design_sha256": digest(DIR / "manifest.json"), "new_api_calls": 0,
              "status": "stronger_baseline_information_diagnostic",
              "rows": rows, "summary": aggregate(rows),
              "recorded_replays": recorded, "recorded_summary": aggregate(recorded)}
    write(OUTPUT, result)
    return result


def timing_audit():
    """Post-hoc per-task timing for the three previously selected model cases."""
    _, episodes = locked()
    saved = json.loads(SOURCE_MODEL.read_text(encoding="utf8"))
    rows = []
    for batch in saved["batches"]:
        template, records = batch["template"], batch["sample"]["records"]
        episode = episodes[template, "tight", "urgent_late", 1.6]
        for label in NEW_POLICIES:
            changed, runtime_policy = adapt(episode, label)
            client = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
            trace, result = run_event_simulation(changed, client, runtime_policy,
                                                 "post-hoc per-task response audit", shared_safety_gate=True)
            client.assert_consumed()
            tasks = []
            for task in episode["task_stream"]:
                starts = [e for e in trace["events"] if e["type"] == "action_started" and e["task_id"] == task["task_id"]]
                finishes = [e for e in trace["events"] if e["type"] == "action_completed" and e["task_id"] == task["task_id"]]
                tasks.append({"task_id": task["task_id"], "device": task["required_action"]["target"],
                              "release_ms": task["release_at_ms"],
                              "start_after_own_release_ms": min(e["timestamp_ms"] for e in starts) - task["release_at_ms"] if starts else None,
                              "finish_after_own_release_ms": min(e["timestamp_ms"] for e in finishes) - task["release_at_ms"] if finishes else None,
                              "deadline_window_ms": task["completion_deadline_ms"] - task["release_at_ms"],
                              "served": result["task_service"][task["task_id"]]})
            rows.append({"template": template, "policy": label,
                         "episode_first_safe_action_ms": result["first_action_start_latency_ms"], "tasks": tasks})
    report = {"status": "post_hoc_per_task_timing_audit", "new_api_calls": 0, "rows": rows,
              "design_sha256": digest(DIR / "manifest.json")}
    write(ROOT / "results" / "c3_information_timing_audit_20260930.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "run", "timing"))
    args = parser.parse_args()
    result = {"prepare": prepare, "run": run, "timing": timing_audit}[args.stage]()
    print(json.dumps({"stage": args.stage, "offline_cells": len(result.get("rows", [])),
                      "recorded_cells": len(result.get("recorded_replays", [])), "new_api_calls": 0}))
