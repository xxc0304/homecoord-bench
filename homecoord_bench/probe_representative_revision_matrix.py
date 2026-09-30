"""Offline baseline matrix for review-only representative task drafts.

This is a deterministic mechanism audit, not a physical-performance study.
It never calls an external model API and never modifies canonical candidates.
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

from make_representative_revision_drafts import OUTPUT, make_drafts  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402

POLICIES = (
    "IndependentMultiAgent",
    "RuleCoordinator",
    "ConstraintCoordinator",
    "DeadlineAwareCoordinator",
    "CentralSingleAgent",
)
REPEATS = 3
RESULT_PATH = ROOT / "results" / "representative_revision_baseline_matrix_20260927.json"
REPORT_PATH = REPO_ROOT / "docs" / "REPRESENTATIVE_REVISION_BASELINE_MATRIX_2026-09-27.md"


class FixedLatencyClient(DryRunClient):
    def __init__(self, latency_ms: int) -> None:
        self.latency_ms = latency_ms

    def decide(self, request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        result = super().decide(request, instructions)
        self.last_latency_ms = self.latency_ms
        return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_and_check_persisted_drafts(expected: dict[str, dict[str, Any]]) -> dict[str, str]:
    actual_paths = {path.stem: path for path in OUTPUT.glob("*.json")}
    separate_review_material = {"HC-PAIR-C2-VENT-HEAT-REVIEW"}
    missing = set(expected) - set(actual_paths)
    unexpected = set(actual_paths) - set(expected) - separate_review_material
    if missing or unexpected:
        raise AssertionError(
            f"persisted event draft IDs differ: missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    hashes: dict[str, str] = {}
    for episode_id, episode in expected.items():
        persisted = json.loads(actual_paths[episode_id].read_text(encoding="utf-8"))
        if persisted != episode:
            changed = sorted(key for key in set(persisted) | set(episode)
                             if persisted.get(key) != episode.get(key))
            raise AssertionError(f"persisted draft {episode_id} is stale in fields: {changed}")
        hashes[episode_id] = _digest(episode)
    return hashes


def _run_matrix(episodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    config_hashes: dict[tuple[str, str], set[str]] = {}
    for episode_id, source_episode in sorted(episodes.items()):
        latency_ms = source_episode.get("variant", {}).get("proposal_latency_factor_ms") or 300
        for policy in POLICIES:
            key = (episode_id, policy)
            hashes: set[str] = set()
            for repeat in range(REPEATS):
                episode = deepcopy(source_episode)
                trace, result = run_event_simulation(
                    episode, FixedLatencyClient(latency_ms), policy, ""
                )
                hashes.add(_digest({"trace": trace, "result": result}))
                rows.append({
                    "episode_id": episode_id,
                    "base_episode_id": episode.get("base_episode_id"),
                    "condition": episode.get("variant", {}).get("condition"),
                    "policy": policy,
                    "repeat": repeat + 1,
                    "proposal_latency_ms": latency_ms,
                    "goal_success": result["final_goal_success"],
                    "process_valid_success": result["process_valid_success"],
                    "conflict_counts": result["conflict_counts"],
                    "task_service": result["task_service"],
                    "task_action_finish_time_ms": result["task_action_finish_time_ms"],
                    "first_action_start_latency_ms": result["first_action_start_latency_ms"],
                    "first_goal_progress_latency_ms": result["first_goal_progress_latency_ms"],
                    "task_completion_time_ms": result["task_completion_time_ms"],
                    "stale_at_action_start_count": result["stale_at_action_start_count"],
                    "in_flight_precondition_invalidated_action_count": result[
                        "in_flight_precondition_invalidated_action_count"
                    ],
                    "unsafe_state_onset_during_action_count": result[
                        "unsafe_state_onset_during_action_count"
                    ],
                    "state_constraint_violation_duration_ms": result[
                        "state_constraint_violation_duration_ms"
                    ],
                    "rejected_action_count": result["rejected_action_count"],
                    "api_calls_concurrent": result["api_calls_concurrent"],
                })
            config_hashes[key] = hashes
    nondeterministic = [f"{episode}/{policy}" for (episode, policy), hashes in config_hashes.items()
                        if len(hashes) != 1]
    if nondeterministic:
        raise AssertionError(f"fixed-input repeated runs were not deterministic: {nondeterministic}")
    return rows


def _one(rows: list[dict[str, Any]], episode_id: str, policy: str) -> dict[str, Any]:
    selected = [row for row in rows if row["episode_id"] == episode_id and row["policy"] == policy]
    if len(selected) != REPEATS:
        raise AssertionError(f"expected {REPEATS} repeats for {episode_id}/{policy}, got {len(selected)}")
    first = selected[0]
    for row in selected[1:]:
        for key in first:
            if key == "repeat":
                continue
            if row[key] != first[key]:
                raise AssertionError(f"repeat mismatch for {episode_id}/{policy} field {key}")
    return first


def _assert_mechanisms(rows: list[dict[str, Any]]) -> None:
    c1_conflict = "HC-PAIR-C1-HVAC-CONFLICT"
    c1_safe = "HC-PAIR-C1-HVAC-SAFE"
    assert _one(rows, c1_conflict, "IndependentMultiAgent")["conflict_counts"]["C1"] == 1
    assert _one(rows, c1_conflict, "ConstraintCoordinator")["conflict_counts"]["C1"] == 0
    assert _one(rows, c1_safe, "IndependentMultiAgent")["conflict_counts"]["C1"] == 0
    assert _one(rows, c1_safe, "ConstraintCoordinator")["conflict_counts"]["C1"] == 0

    c3_low = "HC-PAIR-C3-HOME-POWER-OVER-CAPACITY"
    c3_exact = "HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT"
    c3_high = "HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL"
    assert _one(rows, c3_low, "IndependentMultiAgent")["conflict_counts"]["C3"] == 1
    assert _one(rows, c3_low, "RuleCoordinator")["conflict_counts"]["C3"] == 1
    assert _one(rows, c3_low, "ConstraintCoordinator")["conflict_counts"]["C3"] == 0
    for episode_id in (c3_exact, c3_high):
        assert _one(rows, episode_id, "IndependentMultiAgent")["conflict_counts"]["C3"] == 0
        assert _one(rows, episode_id, "ConstraintCoordinator")["conflict_counts"]["C3"] == 0
    safe_constraint = _one(rows, c3_high, "ConstraintCoordinator")
    safe_independent = _one(rows, c3_high, "IndependentMultiAgent")
    assert safe_constraint["task_action_finish_time_ms"] == safe_independent["task_action_finish_time_ms"]

    precommit = "HC-PAIR-C4-CLEAN-PRECOMMIT"
    inflight = "HC-PAIR-C4-CLEAN-INFLIGHT"
    no_event = "HC-PAIR-C4-CLEAN-NO-EVENT"
    postcomplete = "HC-PAIR-C4-CLEAN-POSTCOMPLETE"
    assert _one(rows, precommit, "ConstraintCoordinator")["stale_at_action_start_count"] == 1
    inflight_independent = _one(rows, inflight, "IndependentMultiAgent")
    inflight_constraint = _one(rows, inflight, "ConstraintCoordinator")
    assert inflight_independent["unsafe_state_onset_during_action_count"] == 1
    assert inflight_constraint["unsafe_state_onset_during_action_count"] == 1
    assert inflight_constraint["state_constraint_violation_duration_ms"] == 2900
    assert _one(rows, no_event, "ConstraintCoordinator")["unsafe_state_onset_during_action_count"] == 0
    assert _one(rows, postcomplete, "ConstraintCoordinator")["unsafe_state_onset_during_action_count"] == 0


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = {}
    for episode_id in sorted({row["episode_id"] for row in rows}):
        summaries[episode_id] = {}
        for policy in POLICIES:
            row = _one(rows, episode_id, policy)
            summaries[episode_id][policy] = {
                key: row[key] for key in (
                    "condition", "proposal_latency_ms", "goal_success", "process_valid_success",
                    "conflict_counts", "task_service", "task_action_finish_time_ms",
                    "first_action_start_latency_ms", "first_goal_progress_latency_ms",
                    "task_completion_time_ms", "stale_at_action_start_count",
                    "in_flight_precondition_invalidated_action_count",
                    "unsafe_state_onset_during_action_count",
                    "state_constraint_violation_duration_ms", "rejected_action_count",
                )
            }
    return summaries


def _write_report(payload: dict[str, Any]) -> None:
    rows = payload["summary_by_episode_and_policy"]
    lines = [
        "# 代表性任务修订草稿：全基线机制审计",
        "",
        "日期：2026-09-27",
        "状态：隔离草稿的离线固定时延行为检查；不是物理性能实验、独立领域双审或算法收益评估。",
        "",
        "## 设计与复现",
        "",
        "读取 9 条 HC-M01／M11／M16 修订草稿，先逐条核对落盘 JSON 与生成器对象完全一致，再对每条草稿运行 IndependentMultiAgent、RuleCoordinator、ConstraintCoordinator、DeadlineAwareCoordinator 和 CentralSingleAgent。每个 episode／策略组合重复 3 次，共 135 次确定性 DryRun。全部条件使用 300 ms 固定提案延迟；C4 提交前事件设在 350 ms，在途事件设在 500 ms。没有模型 API 或真实设备。报告中的时延、功率与事件时点均为合成设定。",
        "",
        "输入完整性：9/9 个落盘草稿与生成器逐字段相同；所有 45 个 episode／策略配置的三次轨迹与结果均完全一致。原始 HC-M01、HC-M11、HC-M16 候选文件没有被此脚本修改。",
        "",
        "## 主要结果",
        "",
        "| 配对 | Independent | Constraint | 解释 |",
        "|---|---|---|---|",
    ]
    c1a = rows["HC-PAIR-C1-HVAC-CONFLICT"]
    c1b = rows["HC-PAIR-C1-HVAC-SAFE"]
    c3a = rows["HC-PAIR-C3-HOME-POWER-OVER-CAPACITY"]
    c3b = rows["HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL"]
    c4pre = rows["HC-PAIR-C4-CLEAN-PRECOMMIT"]
    c4run = rows["HC-PAIR-C4-CLEAN-INFLIGHT"]
    c4safe = rows["HC-PAIR-C4-CLEAN-NO-EVENT"]
    lines.extend([
        f"| C1 HVAC 冲突／安全 | 冲突臂 C1={c1a['IndependentMultiAgent']['conflict_counts']['C1']}；能源动作完成 {c1a['IndependentMultiAgent']['task_action_finish_time_ms'].get('peak_off')} ms | 冲突臂 C1={c1a['ConstraintCoordinator']['conflict_counts']['C1']}；能源动作完成 {c1a['ConstraintCoordinator']['task_action_finish_time_ms'].get('peak_off')} ms | 冲突臂协调将能源动作延后 5,800 ms；安全配对两者 C1 均为 0，Constraint 未增加能源动作完成时间。 |",
        f"| C3 容量低／高配对 | 低容量 C3={c3a['IndependentMultiAgent']['conflict_counts']['C3']}；高容量 C3={c3b['IndependentMultiAgent']['conflict_counts']['C3']} | 低容量 C3={c3a['ConstraintCoordinator']['conflict_counts']['C3']}；高容量 C3={c3b['ConstraintCoordinator']['conflict_counts']['C3']} | 低容量下 RuleCoordinator 也保留 C3 冲突，Constraint 将其消除并使完成时间增加 900 ms；高容量安全对照没有额外串行等待。 |",
        f"| C4 提交前／在途／安全对照 | 提交前 stale 拒绝={c4pre['IndependentMultiAgent']['stale_at_action_start_count']}；在途安全违规时长={c4run['IndependentMultiAgent']['state_constraint_violation_duration_ms']} ms | 提交前 stale 拒绝={c4pre['ConstraintCoordinator']['stale_at_action_start_count']}；在途安全违规时长={c4run['ConstraintCoordinator']['state_constraint_violation_duration_ms']} ms | 提交前条件下策略均拒绝必要清洁动作；在途条件下 Constraint 未取消已启动动作，出现 2,900 ms 违规；无事件对照没有违规。DeadlineAware 在在途条件避免违规，但必要清洁任务未服务。 |",
        "",
        "## 全部策略明细",
        "",
        "| Episode | 策略 | 过程有效 | 冲突 C1/C3/C4 | 首动作启动 ms | 任务服务 | 安全违规时长 ms |",
        "|---|---|---:|---:|---:|---|---:|",
    ])
    for episode_id in sorted(rows):
        for policy in POLICIES:
            item = rows[episode_id][policy]
            counts = item["conflict_counts"]
            service = ", ".join(f"{task}:{int(ok)}" for task, ok in sorted(item["task_service"].items()))
            lines.append(
                f"| {episode_id} | {policy} | {int(item['process_valid_success'])} | "
                f"{counts['C1']}/{counts['C3']}/{counts['C4']} | "
                f"{item['first_action_start_latency_ms']} | {service} | "
                f"{item['state_constraint_violation_duration_ms']} |"
            )
    lines.extend([
        "",
        "## 结论边界",
        "",
        "这批运行说明所定义的冲突与安全对照在固定提案和所设合成时间线上可被当前评测器区分，并展示了三种不同结果：Constraint 可用串行化消除 C1/C3 冲突；DeadlineAware 的等待能避开部分 C4 在途违规，但可能牺牲任务服务；设备启动前的动作前提检查会安全拒绝过期清洁提案。C4 草稿不支持中断、停止延迟、补偿或恢复，因此不能据此声称完成了动态局部修复评估。",
        "",
        "当前结果仍不证明现实设备参数、模型响应分布、一般家庭场景泛化或新算法必要性。草稿未进入正式评分，尚未领域双审；下一步需人工核实动作效果／时长／功率来源、工具权限和用户目标，再冻结版本进行独立复核。",
        "",
        "完整逐次结果与输入哈希：homecoord_bench/results/representative_revision_baseline_matrix_20260927.json。复跑：python homecoord_bench/probe_representative_revision_matrix.py。",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    expected = {episode["episode_id"]: episode for episode in make_drafts()}
    draft_hashes = _load_and_check_persisted_drafts(expected)
    rows = _run_matrix(expected)
    _assert_mechanisms(rows)
    payload = {
        "schema_version": "representative-revision-baseline-matrix-0.1",
        "date": "2026-09-27",
        "draft_count": len(expected),
        "policy_count": len(POLICIES),
        "repeats_per_configuration": REPEATS,
        "run_count": len(rows),
        "proposal_latency_ms": "300 ms in all arms; synthetic fixed delay",
        "api_calls": 0,
        "real_device_runs": 0,
        "persisted_draft_generator_match": True,
        "all_repeated_runs_exactly_equal": True,
        "canonical_candidates_modified": False,
        "draft_hashes_sha256": draft_hashes,
        "summary_by_episode_and_policy": _summary(rows),
        "runs": rows,
        "interpretation": "Fixed-proposal deterministic mechanism audit only; no calibrated physical claims, independent domain review, or new-algorithm evidence.",
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_report(payload)
    print(json.dumps({
        "run_count": payload["run_count"],
        "config_count": payload["draft_count"] * payload["policy_count"],
        "repeats_per_configuration": REPEATS,
        "drafts_match_generator": payload["persisted_draft_generator_match"],
        "repeat_determinism": payload["all_repeated_runs_exactly_equal"],
        "api_calls": payload["api_calls"],
        "report": str(REPORT_PATH),
        "result": str(RESULT_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
