"""Controlled offline probe of cross-agent in-flight precondition invalidation.

Only in-memory copies of two review drafts are changed. No model API or
canonical candidate data is used or modified.
"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402


SOURCE_DIR = ROOT / "revision_drafts" / "20260927"
SOURCES = {
    "conflict": SOURCE_DIR / "HC-PAIR-C1-HVAC-CONFLICT.json",
    "safe": SOURCE_DIR / "HC-PAIR-C1-HVAC-SAFE.json",
}
POLICIES = (
    "IndependentMultiAgent", "RuleCoordinator", "ConstraintCoordinator",
    "DeadlineAwareCoordinator", "CentralSingleAgent",
)
PHASES = ("action_started", "action_completed")
REPEATS = 3
LATENCY_MS = 300
RESULT_PATH = ROOT / "results" / "agent_caused_inflight_probe_20260927.json"
REPORT_PATH = REPO_ROOT / "docs" / "AGENT_CAUSED_INFLIGHT_PROBE_2026-09-27.md"


class FixedLatencyClient(DryRunClient):
    def decide(self, request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        decision = super().decide(request, instructions)
        self.last_latency_ms = LATENCY_MS
        return decision


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def make_probe_episode(source: dict[str, Any], phase: str) -> dict[str, Any]:
    """Add a realistic ongoing-cooling precondition to a review-only copy."""
    if phase not in PHASES:
        raise ValueError(f"unsupported effect phase: {phase}")
    episode = deepcopy(source)
    episode["base_episode_id"] = source["episode_id"]
    episode["episode_id"] = f"{source['episode_id']}-AGENT-{phase.upper()}"
    episode["exogenous_events"] = []
    comfort = next(task for task in episode["task_stream"]
                   if task["task_id"] == "comfort_cool")
    comfort["action_template"]["requires"] = [{
        "path": "devices.living_hvac", "op": "neq", "value": "forced_off",
    }]
    energy = next(item for item in episode["action_grounding"]
                  if item["task_id"] == "peak_off" and item["operation"] == "off")
    energy["start_effects"] = (
        {"devices.living_hvac": "forced_off"} if phase == "action_started" else {}
    )
    energy["completion_effects"] = (
        {"devices.living_hvac": "forced_off"} if phase == "action_completed" else {}
    )
    episode.setdefault("variant", {})["probe_effect_phase"] = phase
    return episode


def _run_config(episode: dict[str, Any], policy: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    digests = set()
    for repeat in range(1, REPEATS + 1):
        trace, result = run_event_simulation(
            deepcopy(episode), FixedLatencyClient(), policy, ""
        )
        digest = _digest({"trace": trace, "result": result})
        digests.add(digest)
        rows.append({
            "repeat": repeat,
            "trace_result_sha256": digest,
            "cross_agent_invalidation_count": result[
                "cross_agent_in_flight_precondition_invalidated_action_count"
            ],
            "invalidation_count": result["in_flight_precondition_invalidated_action_count"],
            "invalidation_source_counts": result[
                "in_flight_precondition_invalidation_source_counts"
            ],
            "invalidation_records": result["in_flight_precondition_invalidations"],
            "c1_conflict_count": result["conflict_counts"]["C1"],
            "process_valid_success": result["process_valid_success"],
            "state_constraint_violation_duration_ms": result[
                "state_constraint_violation_duration_ms"
            ],
            "action_events": [
                {"type": event["type"], "task_id": event["task_id"],
                 "timestamp_ms": event["timestamp_ms"]}
                for event in trace["events"]
                if event["type"] in {"action_started", "action_completed"}
            ],
        })
    if len(digests) != 1:
        raise AssertionError(f"nondeterministic config: {episode['episode_id']}/{policy}")
    return {key: value for key, value in rows[0].items() if key != "repeat"}, rows


def run_probe() -> dict[str, Any]:
    source_hashes = {}
    summary = {}
    runs = []
    for condition, path in SOURCES.items():
        source_bytes = path.read_bytes()
        source_hashes[condition] = hashlib.sha256(source_bytes).hexdigest()
        source = json.loads(source_bytes.decode("utf-8"))
        summary[condition] = {}
        for phase in PHASES:
            episode = make_probe_episode(source, phase)
            summary[condition][phase] = {}
            for policy in POLICIES:
                item, rows = _run_config(episode, policy)
                summary[condition][phase][policy] = item
                runs.extend({"condition": condition, "phase": phase,
                             "policy": policy, **row} for row in rows)

    for phase in PHASES:
        expected_source = {"exogenous_update": 0, "action_started": 0,
                           "action_completed": 0}
        expected_source[phase] = 1
        independent = summary["conflict"][phase]["IndependentMultiAgent"]
        if independent["cross_agent_invalidation_count"] != 1:
            raise AssertionError(f"missing cross-agent invalidation for {phase}")
        if independent["invalidation_source_counts"] != expected_source:
            raise AssertionError(f"wrong source attribution for {phase}")
        for condition, policy in (
            ("conflict", "ConstraintCoordinator"),
            ("safe", "IndependentMultiAgent"),
            ("safe", "ConstraintCoordinator"),
        ):
            if summary[condition][phase][policy]["cross_agent_invalidation_count"] != 0:
                raise AssertionError(f"unexpected invalidation: {condition}/{phase}/{policy}")

    payload = {
        "schema_version": "agent-caused-inflight-probe-0.1",
        "date": "2026-09-27",
        "source_draft_sha256": source_hashes,
        "review_status": "isolated_draft_mechanism_check",
        "proposal_latency_ms": LATENCY_MS,
        "repeats_per_configuration": REPEATS,
        "configuration_count": len(SOURCES) * len(PHASES) * len(POLICIES),
        "run_count": len(runs),
        "all_repeated_runs_exactly_equal": True,
        "api_calls": 0,
        "real_device_runs": 0,
        "summary": summary,
        "runs": runs,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_report(payload)
    return payload


def _write_report(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Agent 动作导致在途前提失效：隔离机制探针",
        "",
        "日期：2026-09-27  ",
        "状态：由两条未双审的 C1 配对草稿派生；只验证指标来源和协调行为，不是物理性能或新算法实验。",
        "",
        "制冷任务在内存中增加 `devices.living_hvac != forced_off` 持续前提；能源 Agent 关闭空调的效果分别放在动作开始或完成。冲突臂在制冷期间发出关闭命令，安全臂等制冷完成后才发出。同一固定 300 ms 提案时延、五种策略、每格三次重复，共 60 次 DryRun；不修改源草稿或正式候选。",
        "",
        "| 关闭效果时点 | 冲突臂 Independent | 冲突臂 Constraint | 安全臂 Independent | 安全臂 Constraint |",
        "|---|---:|---:|---:|---:|",
    ]
    for phase in PHASES:
        label = "动作启动" if phase == "action_started" else "动作完成"
        counts = [
            summary[condition][phase][policy]["cross_agent_invalidation_count"]
            for condition, policy in (
                ("conflict", "IndependentMultiAgent"),
                ("conflict", "ConstraintCoordinator"),
                ("safe", "IndependentMultiAgent"),
                ("safe", "ConstraintCoordinator"),
            )
        ]
        lines.append(f"| {label} | {counts[0]} | {counts[1]} | {counts[2]} | {counts[3]} |")
    lines.extend([
        "",
        "冲突臂 Independent 的失效记录均定位到能源 Agent 的关闭动作，且分别归因于 `action_started` 或 `action_completed`。Constraint 在这两种设定下都推迟了冲突动作；安全臂无需额外处理。全部 20 个配置的三次轨迹与结果各自完全一致。",
        "",
        "探针把新增的 `requires` 当作动作运行期间仍需成立的有效性条件；失效只触发记录，不会自动中断动作。结果说明新增指标能辨别 Agent 间状态干扰及其发生阶段。预设的同设备锁或约束协调已能避免本例，不能从中推出需要新协调算法。动作效果时点、持续时间和提案时延均为合成设定；源任务尚未领域双审。",
        "",
        "复跑：`python homecoord_bench/probe_agent_caused_inflight_invalidation.py`。逐次结果及源草稿哈希：`homecoord_bench/results/agent_caused_inflight_probe_20260927.json`。",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    result = run_probe()
    print(json.dumps({
        "configuration_count": result["configuration_count"],
        "run_count": result["run_count"],
        "all_repeated_runs_exactly_equal": result["all_repeated_runs_exactly_equal"],
        "api_calls": result["api_calls"],
        "report": str(REPORT_PATH),
        "result": str(RESULT_PATH),
    }, ensure_ascii=False, indent=2))
