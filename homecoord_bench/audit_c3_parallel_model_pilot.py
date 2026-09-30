"""Audit completeness, blindness, action correctness, and replay coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from probe_c3_non_nested_templates import TEMPLATES


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "results" / "c3_parallel_model_pilot_20260929.json"
OUTPUT = ROOT / "results" / "c3_parallel_model_pilot_audit_20260929.json"


def audit(source: Path = SOURCE, output: Path | None = OUTPUT) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    errors: list[str] = []
    action_checks = 0
    batches = payload.get("batches", [])
    repetitions = sorted({int(batch["repetition"]) for batch in batches})
    for batch in batches:
        template_id = batch["template_id"]
        expected = {task.task_id: task for task in TEMPLATES[template_id]}
        sample = batch["sample"]
        records = sample.get("records", {})
        if sample.get("errors"):
            errors.append(f"{template_id}/{batch['repetition']}: API errors present")
        if set(records) != set(expected):
            errors.append(f"{template_id}/{batch['repetition']}: incomplete task records")
        order = sorted(records, key=lambda task_id: records[task_id]["logical_latency_ms"])
        if order != sample.get("completion_order"):
            errors.append(f"{template_id}/{batch['repetition']}: completion order mismatch")
        for task_id, record in records.items():
            request_task = record["request"]["task"]
            if "required_action" in request_task or "action_template" in request_task:
                errors.append(f"{template_id}/{task_id}: hidden answer leaked")
            if record["logical_latency_ms"] > sample["parallel_batch_wall_ms"]:
                errors.append(f"{template_id}/{task_id}: completion exceeds batch wall")
            decision = record["decision"]
            task = expected[task_id]
            actions = decision.get("actions", [])
            if decision.get("response_type") != "action_proposal" or len(actions) != 1:
                errors.append(f"{template_id}/{task_id}: not one action proposal")
                continue
            action_checks += 1
            action = actions[0]
            if (action.get("target"), action.get("operation")) != (task.device, task.operation):
                errors.append(f"{template_id}/{task_id}: wrong device action")

    expected_batch_count = len(TEMPLATES) * len(repetitions)
    expected_replays = expected_batch_count * len(payload["design"]["pressures_replayed"]) * len(
        payload["design"]["policies"]
    )
    if len(batches) != expected_batch_count:
        errors.append("batch count mismatch")
    if len(payload.get("replays", [])) != expected_replays:
        errors.append("replay count mismatch")
    report = {
        "schema_version": "c3-parallel-model-pilot-audit-0.1",
        "status": "pass" if not errors else "fail",
        "repetitions": repetitions,
        "batch_count": len(batches),
        "model_call_record_count": sum(len(batch["sample"].get("records", {})) for batch in batches),
        "correct_single_action_proposal_count": action_checks,
        "replay_count": len(payload.get("replays", [])),
        "hidden_answer_leak_count": sum("hidden answer leaked" in error for error in errors),
        "errors": errors,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
