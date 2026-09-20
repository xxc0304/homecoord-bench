"""Create a machine pre-review matrix for candidate HomeCoord-Bench episodes.

This is a preparation aid for human double review.  It checks structural and
deterministic properties, but it does not certify physical realism or replace
two independent reviewers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluate import ROOT, load_json, validate_episode_shape


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def audit_episode(episode: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    errors = validate_episode_shape(episode)
    checks["minimum_shape"] = not errors
    if errors:
        notes.extend(errors)

    agents = episode.get("agents", [])
    agent_ids = [agent.get("agent_id") for agent in agents]
    checks["distinct_agents"] = len(agent_ids) >= 2 and len(set(agent_ids)) == len(agent_ids)
    if not checks["distinct_agents"]:
        notes.append("agents must have at least two unique agent_id values")

    tasks = episode.get("task_stream", [])
    groundings = episode.get("action_grounding", [])
    grounding_keys = {
        (item.get("agent_id"), item.get("task_id"), item.get("operation"))
        for item in groundings
    }
    action_templates_ok = True
    grounding_ok = True
    required_actions = 0
    for task in tasks:
        required = task.get("required_action")
        if not required:
            continue
        required_actions += 1
        template = task.get("action_template")
        if not template or template.get("target") != required.get("target") or template.get("operation") != required.get("operation"):
            action_templates_ok = False
            notes.append(f"{task.get('task_id')}: action_template does not match required_action")
        if not any(
            item.get("agent_id") == task.get("agent_id")
            and item.get("task_id") == task.get("task_id")
            and item.get("operation") == required.get("operation")
            for item in groundings
        ):
            grounding_ok = False
            notes.append(f"{task.get('task_id')}: missing action_grounding record")
    checks["required_actions_have_templates"] = action_templates_ok and required_actions > 0
    checks["required_actions_have_grounding"] = grounding_ok and required_actions > 0

    numeric_ok = True
    for item in groundings:
        if not _number(item.get("duration_ms")) or not _number(item.get("power_kw")):
            numeric_ok = False
            notes.append(f"grounding {item.get('task_id')}: duration_ms/power_kw must be non-negative numbers")
    checks["grounding_has_numeric_effect_costs"] = numeric_ok and bool(groundings)

    task_ids = {task.get("task_id") for task in tasks}
    agent_set = set(agent_ids)
    checks["task_references_valid"] = all(
        task.get("agent_id") in agent_set and task.get("task_id") for task in tasks
    )
    checks["grounding_references_valid"] = all(
        item.get("agent_id") in agent_set and item.get("task_id") in task_ids for item in groundings
    )
    if not checks["task_references_valid"]:
        notes.append("task_stream contains an invalid agent or task id")
    if not checks["grounding_references_valid"]:
        notes.append("action_grounding contains an invalid agent or task id")

    pair_set = {
        frozenset(((item.get("target"), item.get("grounded_operation"))) for item in groundings)
    }
    conflict_ok = True
    for rule in episode.get("conflict_rules", []):
        if rule.get("type") in {"C1", "C2"}:
            pair = frozenset(((rule.get("a", {}).get("target"), rule.get("a", {}).get("operation")),
                              (rule.get("b", {}).get("target"), rule.get("b", {}).get("operation"))))
            if pair not in pair_set:
                conflict_ok = False
                notes.append(f"{rule.get('type')}: conflict pair is not represented in action_grounding")
            if rule.get("type") == "C2":
                left = next((item for item in groundings if (item.get("target"), item.get("grounded_operation")) ==
                             (rule.get("a", {}).get("target"), rule.get("a", {}).get("operation"))), None)
                right = next((item for item in groundings if (item.get("target"), item.get("grounded_operation")) ==
                              (rule.get("b", {}).get("target"), rule.get("b", {}).get("operation"))), None)
                left_effects = left.get("environment_effects", {}) if left else {}
                right_effects = right.get("environment_effects", {}) if right else {}
                shared = set(left_effects) & set(right_effects)
                opposite = any(
                    isinstance(left_effects[path], (int, float))
                    and isinstance(right_effects[path], (int, float))
                    and left_effects[path] * right_effects[path] < 0
                    for path in shared
                )
                if not opposite:
                    conflict_ok = False
                    notes.append(f"C2: {rule.get('a', {}).get('target')} and {rule.get('b', {}).get('target')} lack an explicit shared variable with opposite effects")
        elif rule.get("type") == "C3" and not _number(rule.get("capacity")):
            conflict_ok = False
            notes.append("C3: capacity must be a positive numeric value")
    checks["conflict_rules_grounded"] = conflict_ok

    events = episode.get("exogenous_events", [])
    checks["event_versions_monotonic"] = all(
        later.get("new_state_version", 0) > earlier.get("new_state_version", 0)
        for earlier, later in zip(events, events[1:])
    )
    if not checks["event_versions_monotonic"] and events:
        notes.append("exogenous event state versions are not strictly increasing")

    calibration = episode.get("calibration", {})
    calibration_status = calibration.get("status", "missing")
    if calibration_status != "physical_trace_calibrated":
        notes.append("duration, power and effect values still need simulator/device calibration")

    passed = all(checks.values())
    return {
        "episode_id": episode.get("episode_id"),
        "task_family": episode.get("task_family"),
        "review_status": episode.get("review_status"),
        "pre_review_pass": passed,
        "checks": checks,
        "calibration_status": calibration_status,
        "required_action_count": required_actions,
        "notes": notes,
    }


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# HomeCoord-Bench 候选任务预审矩阵 v0.1",
        "",
        "这是一份机器预审结果，不等同于人工双审或物理真实性认证。人工审核者需要分别确认动作语义、优先级、冲突规则和效果参数。",
        "",
        "| Episode | 家族 | 结构/引用检查 | 冲突可判定 | 校准状态 | 机器预审 | 审核人 A | 审核人 B |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        checks = row["checks"]
        structure = all(checks.get(key, False) for key in (
            "minimum_shape", "distinct_agents", "required_actions_have_templates",
            "required_actions_have_grounding", "grounding_has_numeric_effect_costs",
            "task_references_valid", "grounding_references_valid",
        ))
        conflict = checks.get("conflict_rules_grounded", False)
        lines.append(
            f"| {row['episode_id']} | {row['task_family']} | "
            f"{'通过' if structure else '需修正'} | "
            f"{'通过' if conflict else '需修正'} | {row['calibration_status']} | "
            f"{'通过' if row['pre_review_pass'] else '需修正'} | 待填写 | 待填写 |"
        )
    lines.extend([
        "",
        "## 人工审核重点",
        "",
        "1. 检查动作效果、持续时间和功耗是否有模拟器、设备日志或公开规格来源。",
        "2. 检查冲突规则是否代表真实的安全、舒适或资源约束，而不是为了制造冲突而添加。",
        "3. 检查拒绝、延迟或过期动作后的任务服务率是否符合任务语义。",
        "4. 两名审核者独立填写后再讨论分歧；在此之前任务保持 `candidate_dry_run`。",
    ])
    return "\n".join(lines) + "\n"


def run(candidates_dir: Path, output_json: Path, output_markdown: Path) -> list[dict[str, Any]]:
    rows = [audit_episode(load_json(path)) for path in sorted(candidates_dir.glob("*.json"))]
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    output_markdown.write_text(_markdown(rows), encoding="utf-8")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-dir", type=Path, default=ROOT / "data" / "candidates")
    parser.add_argument("--output-json", type=Path, default=ROOT / "results" / "candidate_pre_review_20260920.json")
    parser.add_argument("--output-markdown", type=Path, default=ROOT.parent / "docs" / "HOMECOORD_BENCH_REVIEW_MATRIX_v0.1.md")
    args = parser.parse_args()
    rows = run(args.candidates_dir, args.output_json, args.output_markdown)
    print(json.dumps({"episodes": len(rows), "pre_review_pass": sum(row["pre_review_pass"] for row in rows), "calibration_pending": sum(row["calibration_status"] != "physical_trace_calibrated" for row in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
