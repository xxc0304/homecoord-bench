"""Audit future-task blindness and paired C3 factor isolation without API calls."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from probe_c3_future_pair import SOURCE
from probe_c3_information_boundary import POLICIES
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_parallel_model_pilot import PRESSURES
from probe_c3_robust_reserve_baseline import potential_urgent_metadata
from probe_c3_staggered_release import release_order_records
from probe_c3_structural_generalization import make_episode_from_specs
from probe_c3_uncertain_arrival_grid import ARRIVALS_S, make_arrival_case
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "c3_online_information_contract_20260929.json"


def _visible_requests(episode: dict[str, Any], records: dict[str, Any],
                      policy: str, template_id: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    configured = deepcopy(episode)
    configured["simulation"]["blind_future_task_arrivals"] = True
    if policy == "RobustReserveCoordinator":
        configured["simulation"]["potential_urgent"] = potential_urgent_metadata(template_id)
    ordered = release_order_records(configured, records)
    client = MemoryReplayClient(deepcopy(ordered))
    trace, _ = run_event_simulation(
        configured, client, policy, "online information contract audit",
        shared_safety_gate=True,
    )
    client.assert_consumed()
    return ({request["task"]["task_id"]: request for request in trace["agent_requests"]},
            trace["events"])


def _pair_isolation(absent: dict[str, Any], present: dict[str, Any],
                    arrival_s: int) -> list[str]:
    """Only the urgent task and its metadata may differ between a pair."""
    errors = []
    absent_tasks = {task["task_id"]: task for task in absent["task_stream"]}
    present_tasks = {task["task_id"]: task for task in present["task_stream"]}
    if set(present_tasks) - set(absent_tasks) != {min(
        present["task_stream"], key=lambda task: (
            task["completion_deadline_ms"], task["task_id"]
        ))["task_id"]}:
        errors.append("pair must differ by exactly one urgent task")
    for task_id, task in absent_tasks.items():
        if task != present_tasks.get(task_id):
            errors.append(f"retained task changed: {task_id}")
    for field in ("initial_state", "conflict_rules", "constraints", "exogenous_events"):
        if absent[field] != present[field]:
            errors.append(f"shared field changed: {field}")
    if absent["home"]["resources"]["max_power_kw"] != present["home"]["resources"]["max_power_kw"]:
        errors.append("paired capacity changed")
    if {item["agent_id"]: item for item in absent["agents"]} != {
        item["agent_id"]: item for item in present["agents"]
        if item["agent_id"] in {agent["agent_id"] for agent in absent["agents"]}
    }:
        errors.append("retained agent changed")
    urgent = next(task for task in present["task_stream"]
                  if task["task_id"] not in absent_tasks)
    if urgent["release_at_ms"] != arrival_s * 1000:
        errors.append("urgent release time mismatch")
    return errors


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    saved = json.loads(source.read_text(encoding="utf-8"))
    batches = {batch["template_id"]: batch for batch in saved["batches"]
               if batch["repetition"] == 1}
    errors: list[str] = []
    checked = 0
    for template_id, specs in TEMPLATES.items():
        records = batches[template_id]["sample"]["records"]
        for pressure in PRESSURES:
            base = make_episode_from_specs(template_id, specs, pressure)
            absent = make_arrival_case(base, None)
            for policy in POLICIES:
                baseline, baseline_events = _visible_requests(absent, records, policy, template_id)
                for arrival_s in ARRIVALS_S:
                    present = make_arrival_case(base, arrival_s)
                    pair_errors = _pair_isolation(absent, present, arrival_s)
                    if pair_errors:
                        errors.extend(f"{template_id}/{pressure}/{arrival_s}: {error}"
                                      for error in pair_errors)
                    comparison, comparison_events = _visible_requests(present, records, policy, template_id)
                    for task_id, request in baseline.items():
                        if comparison.get(task_id) != request:
                            errors.append(
                                f"{template_id}/{pressure}/{arrival_s}/{policy}/{task_id}: "
                                "pre-release agent request differs"
                            )
                    cutoff = arrival_s * 1000
                    if ([event for event in baseline_events if event["timestamp_ms"] < cutoff]
                            != [event for event in comparison_events if event["timestamp_ms"] < cutoff]):
                        errors.append(
                            f"{template_id}/{pressure}/{arrival_s}/{policy}: "
                            "pre-release execution trace differs"
                        )
                    checked += 1
    report = {
        "schema_version": "c3-online-information-contract-0.1",
        "status": "exploratory_information_contract_not_benchmark_freeze",
        "new_api_calls": 0,
        "independent_templates": len(TEMPLATES),
        "paired_policy_conditions_checked": checked,
        "all_pre_release_requests_identical_within_pair": not errors,
        "all_pre_release_execution_traces_identical_within_pair": not errors,
        "factor_isolation_errors": errors,
        "limits": [
            "One saved model batch per template was used for request construction; this is an input audit, not a performance estimate.",
            "Future task metadata remains available only to the privileged reference policy.",
            "These two author-designed templates are not a frozen or independently reviewed dataset.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise AssertionError(f"online information contract failed: {errors[:5]}")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({key: result[key] for key in (
        "paired_policy_conditions_checked", "all_pre_release_requests_identical_within_pair",
        "all_pre_release_execution_traces_identical_within_pair",
        "factor_isolation_errors", "new_api_calls",
    )}, ensure_ascii=False, indent=2))
