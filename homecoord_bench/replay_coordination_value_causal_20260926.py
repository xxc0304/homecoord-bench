"""Re-evaluate the September 26 model decisions after causal runtime fixes.

No model is called. The original proposal content and measured logical call
latencies are replayed against both independent execution and an online gate.
"""

from __future__ import annotations

import json
from collections import defaultdict

from audit_candidate_tradeoffs import safe_control
from evaluate import ROOT, load_json
from run_coordination_value_pilot import difference, metrics
from run_protocol_pilot import INSTRUCTIONS
from runtime.execution import run_closed_loop_episode
from runtime.replay_client import MemoryReplayClient


PRIOR = ROOT / "results" / "coordination_value_pilot_20260926.json"
MODEL_LOG = ROOT / "runs" / "coordination_value_pilot_20260926" / "model_events.jsonl"
OUTPUT = ROOT / "results" / "coordination_value_pilot_causal_replay_20260926.json"


def model_decisions_by_episode() -> dict[str, list[dict]]:
    events = [json.loads(line) for line in MODEL_LOG.read_text(encoding="utf-8").splitlines() if line]
    started = {event["request_id"]: event for event in events if event["event_type"] == "model_call_started"}
    grouped = defaultdict(list)
    for event in events:
        if event["event_type"] != "model_call_completed":
            continue
        request = started[event["request_id"]]
        grouped[request["episode_id"]].append({
            "task_id": request["task_id"], "decision": event["decision"],
        })
    return dict(grouped)


def run() -> dict:
    prior = load_json(PRIOR)
    decisions = model_decisions_by_episode()
    rows = []
    for old in prior["rows"]:
        if "error_type" in old:
            rows.append({"episode_id": old["episode_id"], "excluded": old["error_type"]})
            continue
        episode = load_json(ROOT / "data" / "candidates" / f"{old['base_episode_id']}.json")
        if old["condition"] == "matched_safe":
            episode = safe_control(episode)[0]
        model_records = decisions[episode["episode_id"]]
        task_order = [task["task_id"] for task in episode["task_stream"]]
        assert [record["task_id"] for record in model_records] == task_order
        latencies = old["model_call_latencies_ms"]
        assert len(model_records) == len(latencies)
        records = [
            {"decision": record["decision"], "logical_latency_ms": latency}
            for record, latency in zip(model_records, latencies)
        ]
        outcomes = {}
        for architecture in ("IndependentMultiAgent", "ConstraintCoordinator"):
            client = MemoryReplayClient(records)
            trace, result = run_closed_loop_episode(
                episode, client, architecture, INSTRUCTIONS, synthetic_latency=False
            )
            client.assert_consumed()
            outcomes[architecture] = metrics(trace, result, episode["episode_release_at_ms"])
            outcomes[architecture]["device_precondition_rejections"] = sum(
                event.get("reason") in {"unsafe_precondition", "stale_state"}
                for event in trace["events"] if event["type"] == "coordination_decision"
            )
        independent = outcomes["IndependentMultiAgent"]
        strong = outcomes["ConstraintCoordinator"]
        rows.append({
            "episode_id": episode["episode_id"], "condition": old["condition"],
            "family": episode["task_family"], "independent": independent,
            "strong_online": strong,
            "delta_goal_first_satisfied_ms": difference(strong, independent, "goal_first_satisfied_ms"),
            "delta_last_action_end_ms": difference(strong, independent, "last_action_end_ms"),
            "old_independent_valid": old["independent"]["process_valid_success"],
            "old_strong_valid": old["strong_same_proposals"]["process_valid_success"],
        })
    report = {
        "experiment": "causal_replay_of_coordination_value_pilot",
        "status": "stored_real_model_decisions_synthetic_devices_no_new_api_calls",
        "changes": ["enforce action preconditions for all architectures",
                    "coordinator may not inspect future proposals",
                    "coordinator checks current policy constraints"],
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run()
    for row in report["rows"]:
        print(json.dumps({
            "episode_id": row["episode_id"],
            "independent_valid": row.get("independent", {}).get("process_valid_success"),
            "strong_valid": row.get("strong_online", {}).get("process_valid_success"),
            "goal_delta_ms": row.get("delta_goal_first_satisfied_ms"),
            "precondition_rejections": row.get("independent", {}).get("device_precondition_rejections"),
            "excluded": row.get("excluded"),
        }, ensure_ascii=False))
