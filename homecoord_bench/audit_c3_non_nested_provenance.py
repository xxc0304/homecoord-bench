"""Audit provenance coverage against the executable non-nested C3 templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from probe_c3_non_nested_templates import TEMPLATES


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "c3_non_nested_parameter_provenance_v0.1.json"
OUTPUT = ROOT / "results" / "c3_non_nested_provenance_audit_20260929.json"


def audit(source: Path = SOURCE, output: Path | None = OUTPUT) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    records = {
        (row["template_id"], row["task_id"]): row for row in payload["records"]
    }
    expected = {
        (template_id, task.task_id): task
        for template_id, tasks in TEMPLATES.items()
        for task in tasks
    }
    errors: list[str] = []
    if set(records) != set(expected):
        errors.append(
            f"record keys differ: missing={sorted(set(expected)-set(records))}, "
            f"extra={sorted(set(records)-set(expected))}"
        )
    unresolved: list[dict[str, str]] = []
    exact_power_count = 0
    exact_duration_count = 0
    for key, task in expected.items():
        row = records.get(key)
        if not row:
            continue
        configured = row["configured"]
        actual = {
            "power_kw": task.power_kw,
            "duration_min": task.duration_min,
            "deadline_min": task.deadline_min,
        }
        if configured != actual:
            errors.append(f"{key}: provenance configured={configured}, executable={actual}")
        power = row["power_evidence"]
        if power.get("level") == "E2":
            exact_power_count += 1
            if float(power["value_kw"]) != task.power_kw:
                errors.append(f"{key}: E2 power does not match executable value")
            if not power.get("url"):
                errors.append(f"{key}: E2 power lacks URL")
        else:
            unresolved.append({"template_id": key[0], "task_id": key[1], "field": "power_kw"})
        duration = row["duration_evidence"]
        if duration.get("level") == "E2":
            exact_duration_count += 1
            if int(duration["value_min"]) != task.duration_min:
                errors.append(f"{key}: E2 duration does not match executable value")
        else:
            unresolved.append({"template_id": key[0], "task_id": key[1], "field": "duration_min"})

    report = {
        "schema_version": "c3-non-nested-provenance-audit-0.1",
        "status": "pass_with_declared_gaps" if not errors else "fail",
        "record_count": len(records),
        "exact_e2_power_count": exact_power_count,
        "exact_e2_duration_count": exact_duration_count,
        "unresolved_field_count": len(unresolved),
        "unresolved": unresolved,
        "errors": errors,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
