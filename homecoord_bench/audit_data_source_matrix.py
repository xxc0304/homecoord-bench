"""Audit the machine-readable C1-C4 evidence and claim boundaries."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MATRIX = ROOT / "data" / "data_source_matrix_v0.1.json"


def audit(matrix: dict) -> list[str]:
    errors: list[str] = []
    allowed = set(matrix.get("allowed_evidence_levels", []))
    expected_families = {"C1", "C2", "C3", "C4"}
    families = matrix.get("families", [])

    seen = [item.get("family") for item in families]
    if set(seen) != expected_families or len(seen) != len(expected_families):
        errors.append(f"families must be exactly C1-C4 once each; got {seen}")

    for item in families:
        family = item.get("family", "<missing>")
        minimum = set(item.get("minimum_evidence", []))
        available = set(item.get("available_evidence", []))
        unknown = (minimum | available) - allowed
        if unknown:
            errors.append(f"{family}: unknown evidence levels {sorted(unknown)}")
        for field in (
            "claim",
            "readiness",
            "permitted_claims",
            "prohibited_claims",
            "next_evidence",
        ):
            if not item.get(field):
                errors.append(f"{family}: missing {field}")
        overlap = set(item.get("permitted_claims", [])) & set(
            item.get("prohibited_claims", [])
        )
        if overlap:
            errors.append(f"{family}: claims both permitted and prohibited: {sorted(overlap)}")

    return errors


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    errors = audit(matrix)
    result = {
        "matrix": str(MATRIX.relative_to(ROOT.parent)),
        "families": len(matrix.get("families", [])),
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
