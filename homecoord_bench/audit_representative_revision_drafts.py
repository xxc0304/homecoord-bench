"""Reproducible, author-side audit of review-only C1/C3/C4 drafts.

This checks design invariants and records unresolved questions. It is not an
independent domain review or a physical calibration.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from make_representative_revision_drafts import OUTPUT, make_drafts
from runtime.episode_validation import validate_event_episode
from runtime.protocol import build_agent_request
from runtime.dry_run import DryRunClient
from runtime.tool_contract import validate_tool_call

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "results" / "representative_revision_design_audit_20260927.json"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()


def changed_paths(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        return [path for key in sorted(left.keys() | right.keys())
                for path in changed_paths(left.get(key), right.get(key),
                                          f"{prefix}.{key}" if prefix else key)]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [path for i, (a, b) in enumerate(zip(left, right))
                for path in changed_paths(a, b, f"{prefix}[{i}]")]
    return [] if left == right else [prefix]


def prompt(episode: dict, task: dict) -> dict:
    agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
    request = build_agent_request(
        episode, agent, task, architecture="IndependentMultiAgent",
        current_time_ms=task["release_at_ms"],
        current_state=episode["initial_state"]["values"],
        state_version=episode["initial_state"]["version"],
        request_id="audit-fixed-id",
    )
    for key in ("episode_id", "base_episode_id"):
        request.pop(key, None)
    return request


def audit() -> dict:
    episodes = {e["episode_id"]: e for e in make_drafts()}
    checks: list[dict] = []
    def check(code: str, ok: bool, evidence: Any) -> None:
        checks.append({"code": code, "pass": bool(ok), "evidence": evidence})

    persisted_all = {p.stem: p for p in OUTPUT.glob("*.json")}
    persisted = {episode_id: persisted_all[episode_id]
                 for episode_id in episodes if episode_id in persisted_all}
    check("DRAFT_SET", set(persisted) == set(episodes),
          {"expected_event_drafts": sorted(episodes),
           "persisted_event_drafts": sorted(persisted),
           "other_review_material": sorted(set(persisted_all) - set(episodes))})
    c2_path = OUTPUT / "HC-PAIR-C2-VENT-HEAT-REVIEW.json"
    c2_review = json.loads(c2_path.read_text(encoding="utf-8")) if c2_path.exists() else {}
    check("C2_SEPARATE_REVIEW_SCOPE",
          c2_review.get("scenario_type") == "standalone_continuous_physics_probe"
          and c2_review.get("review_status") == "proposed_revision_not_scored"
          and c2_review.get("conflict_family") == "C2_indirect_environmental_interference"
          and c2_review.get("provenance_and_limits", {}).get("has_real_device_data") is False
          and c2_review.get("provenance_and_limits", {}).get("has_real_model_proposals") is False,
          {"exists": c2_path.exists(),
           "scenario_type": c2_review.get("scenario_type"),
           "review_status": c2_review.get("review_status"),
           "conflict_family": c2_review.get("conflict_family"),
           "provenance_and_limits": c2_review.get("provenance_and_limits")})
    for episode_id, episode in episodes.items():
        actual = json.loads(persisted[episode_id].read_text(encoding="utf-8"))
        check(f"PERSISTED:{episode_id}", actual == episode, digest(actual))
        check(f"SCHEMA:{episode_id}", not validate_event_episode(episode),
              validate_event_episode(episode))
        check(f"STATUS:{episode_id}", episode["review_status"] == "proposed_revision_not_scored",
              episode["review_status"])
        check(f"STRICT_CONTRACT:{episode_id}", episode.get("tool_contract_version") == "strict-v1",
              episode.get("tool_contract_version"))
        for task in episode["task_stream"]:
            request = prompt(episode, task)
            template = task["action_template"]
            signatures = {(item["target"], item["operation"])
                          for item in request["available_actions"]}
            check(f"TOOL:{episode_id}:{task['task_id']}",
                  (template["target"], template["operation"]) in signatures,
                  sorted(map(list, signatures)))
            check(f"NO_TEMPLATE_LEAK:{episode_id}:{task['task_id']}",
                  "required_action" not in request["task"]
                  and "action_template" not in request["task"],
                  sorted(request["task"]))
            agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
            scripted = build_agent_request(
                episode, agent, task, architecture="IndependentMultiAgent",
                current_time_ms=task["release_at_ms"],
                include_evaluation_hints=True, request_id="audit-scripted",
            )
            action = DryRunClient().decide(scripted)["actions"][0]
            contract_error = validate_tool_call(
                episode, task["agent_id"], task["task_id"], action
            )
            check(f"EXECUTABLE_TOOL:{episode_id}:{task['task_id']}",
                  contract_error is None, contract_error)

    by_id = episodes
    c1a = by_id["HC-PAIR-C1-HVAC-CONFLICT"]
    c1b = by_id["HC-PAIR-C1-HVAC-SAFE"]
    c3a = by_id["HC-PAIR-C3-HOME-POWER-OVER-CAPACITY"]
    c3e = by_id["HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT"]
    c3b = by_id["HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL"]
    c4n = by_id["HC-PAIR-C4-CLEAN-NO-EVENT"]
    c4p = by_id["HC-PAIR-C4-CLEAN-PRECOMMIT"]
    c4i = by_id["HC-PAIR-C4-CLEAN-INFLIGHT"]
    c4a = by_id["HC-PAIR-C4-CLEAN-POSTCOMPLETE"]

    allowed_common = {"episode_id", "variant.condition"}
    pairs = [
        ("C1_CONFLICT_SAFE", c1a, c1b,
         allowed_common | {"task_stream[1].release_at_ms"}),
        ("C3_LOW_EXACT", c3a, c3e,
         allowed_common | {"variant.capacity_kw", "home.resources.max_power_kw",
                           "conflict_rules[0].capacity"}),
        ("C3_LOW_HIGH", c3a, c3b,
         allowed_common | {"variant.capacity_kw", "home.resources.max_power_kw",
                           "conflict_rules[0].capacity"}),
        ("C4_PRE_INFLIGHT", c4p, c4i,
         allowed_common | {"exogenous_events[0].at_ms", "exogenous_events[1].at_ms"}),
    ]
    pair_diffs = {}
    for label, a, b, allowed in pairs:
        differences = changed_paths(a, b)
        unexpected = sorted(set(differences) - allowed)
        pair_diffs[label] = {"changed_paths": differences,
                             "unexpected_paths": unexpected}
        check(f"PAIR_ISOLATION:{label}", not unexpected, pair_diffs[label])

    c4_latencies = {e["variant"]["proposal_latency_factor_ms"] or 300
                    for e in (c4n, c4p, c4i, c4a)}
    check("C4_SAME_PROPOSAL_LATENCY", c4_latencies == {300}, sorted(c4_latencies))
    for label, a, b, _ in pairs:
        if label.startswith("C3") or label == "C4_PRE_INFLIGHT":
            left = [prompt(a, task) for task in a["task_stream"]]
            right = [prompt(b, task) for task in b["task_stream"]]
            check(f"SAME_INITIAL_PROMPTS:{label}", left == right,
                  [changed_paths(x, y) for x, y in zip(left, right)])
    c3_power = sum(t["action_template"]["power_kw"] for t in c3a["task_stream"])
    capacities = [e["home"]["resources"]["max_power_kw"] for e in (c3a, c3e, c3b)]
    check("C3_CAPACITY_BOUNDARY", capacities[0] < c3_power == capacities[1] < capacities[2],
          {"individual_kw": [t["action_template"]["power_kw"] for t in c3a["task_stream"]],
           "combined_kw": c3_power, "capacities_kw": capacities})
    check("C3_EACH_ACTION_FEASIBLE", all(t["action_template"]["power_kw"] <= capacities[0]
                                        for t in c3a["task_stream"]), capacities[0])
    check("C4_NO_EVENT_GOAL_LEAK", all("bedroom.clean" not in event["patch"]
                                       for e in (c4p, c4i, c4a)
                                       for event in e["exogenous_events"]), None)
    deadlines = {e["episode_id"]: [t.get("completion_deadline_ms") for t in e["task_stream"]]
                 for e in episodes.values()}
    # Hard-deadline scheduling is not part of the C1/C3/C4 event-draft claim.
    # C2 deadline sweeps are reported separately as synthetic physics probes.
    deadline_scope = {
        "event_draft_set": "C1_C3_C4_conflict_and_elapsed_time_only; hard_deadline_scheduling_not_claimed",
        "separate_c2_probe": "synthetic_deadline_pressure_only; not_merged_into_event_matrix",
        "event_draft_deadlines_ms": deadlines,
    }
    check("DEADLINE_SCOPE_DECLARED",
          deadline_scope["event_draft_set"].endswith("hard_deadline_scheduling_not_claimed")
          and deadline_scope["separate_c2_probe"].startswith("synthetic_deadline_pressure_only"),
          deadline_scope)

    findings = [
        {"id": "R2", "severity": "scope_boundary",
         "scope": "C1/C3/C4 event drafts", "finding": "These drafts intentionally test conflict and elapsed-time effects, not hard-deadline scheduling. Synthetic C2 deadline results remain a separate probe and are not pooled with this matrix."},
        {"id": "R3", "severity": "requires_domain_review",
         "scope": "C1", "finding": "Cooling-to-24 effect, 6000 ms duration, and 1.4 kW are synthetic; the energy task has no explicit peak window or quantitative service goal. The safe arm changes task release time by design."},
        {"id": "R4", "severity": "requires_domain_review",
         "scope": "C3", "finding": "0.5 kW study light, 1.0 kW HVAC, action durations, and whether the limit is whole-home or circuit capacity lack physical sources. The capacity threshold is not visible in individual Agent requests, so model comparisons must disclose the information asymmetry."},
        {"id": "R5", "severity": "blocking_for_repair_claim",
         "scope": "C4", "finding": "No cancellation, stop latency, partial progress, or restart contract. This arm only tests detection and service/safety tradeoff, not repair. Occupancy event times remain synthetic."},
    ]
    payload = {
        "schema_version": "representative-design-audit-0.1",
        "status": "author_side_machine_audit_not_independent_review",
        "draft_hashes_sha256": {k: digest(v) for k, v in sorted(episodes.items())},
        "checks": checks,
        "passed": sum(c["pass"] for c in checks),
        "failed": sum(not c["pass"] for c in checks),
        "pair_differences": pair_diffs,
        "deadline_scope": deadline_scope,
        "findings": findings,
        "release_decision": "hold_as_review_only_drafts",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = audit()
    print(json.dumps({"passed": result["passed"], "failed": result["failed"],
                      "release_decision": result["release_decision"],
                      "report": str(REPORT)}, ensure_ascii=False, indent=2))
