"""Run the offline event-simulation checks and refresh their result files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from audit_event_grounding import audit  # noqa: E402
from audit_event_episode_validity import audit as audit_episode_validity  # noqa: E402
from audit_external_goal_credit import audit as audit_external_goal_credit  # noqa: E402
from audit_deadline_feasibility import audit as audit_deadline_feasibility  # noqa: E402
from audit_baseline_coverage import audit as audit_baseline_coverage  # noqa: E402
from probe_event_deadline_sensitivity import run as run_deadline_sensitivity  # noqa: E402
from probe_proposal_order_sensitivity import run as run_order_sensitivity  # noqa: E402
from run_event_simulation_matrix import run_matrix  # noqa: E402
from run_recorded_event_replay import run as run_recorded_replay  # noqa: E402


def _run_tests() -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"HomeCoord-Bench tests failed:\n{output}")
    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    if not match:
        raise RuntimeError(f"Could not read unittest count from output:\n{output}")
    return int(match.group(1)), output


def run_suite(*, skip_tests: bool = False) -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    test_count = None
    if not skip_tests:
        test_count, _ = _run_tests()

    matrix_path = RESULTS / "event_simulation_matrix_20260926.json"
    replay_path = RESULTS / "recorded_event_replay_20260926.json"
    deadline_path = RESULTS / "event_deadline_sensitivity_20260926.json"
    order_path = RESULTS / "proposal_order_sensitivity_20260926.json"
    audit_path = RESULTS / "event_grounding_audit_20260926.json"
    episode_validity_path = RESULTS / "event_episode_validation_20260926.json"
    external_goal_credit_path = RESULTS / "external_goal_credit_audit_20260927.json"
    deadline_feasibility_path = RESULTS / "deadline_feasibility_audit_20260926.json"
    baseline_coverage_path = RESULTS / "baseline_coverage_audit_20260926.json"
    matrix = run_matrix(matrix_path)
    replay = run_recorded_replay(replay_path)
    deadline = run_deadline_sensitivity(deadline_path)
    order = run_order_sensitivity(order_path)
    grounding = audit()
    audit_path.write_text(json.dumps(grounding, ensure_ascii=False, indent=2), encoding="utf-8")
    episode_validity = audit_episode_validity()
    episode_validity_path.write_text(
        json.dumps(episode_validity, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    external_goal_credit = audit_external_goal_credit()
    external_goal_credit_path.write_text(
        json.dumps(external_goal_credit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    deadline_feasibility = audit_deadline_feasibility()
    deadline_feasibility_path.write_text(
        json.dumps(deadline_feasibility, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    baseline_coverage = audit_baseline_coverage()
    baseline_coverage_path.write_text(
        json.dumps(baseline_coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if matrix["error_count"]:
        raise RuntimeError(f"Event matrix reported {matrix['error_count']} errors")
    if episode_validity["invalid_count"]:
        raise RuntimeError(
            f"Event episode validation found {episode_validity['invalid_count']} invalid files"
        )
    if external_goal_credit["error_count"]:
        raise RuntimeError(
            f"External-only goal audit found {external_goal_credit['error_count']} invalid files"
        )
    if (replay["network_calls"] != 0 or deadline["network_calls"] != 0
            or order["network_calls"] != 0):
        raise RuntimeError("Offline replay unexpectedly recorded network calls")

    summary = {
        "schema_version": "event-pilot-suite-0.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "test_count": test_count,
        "test_status": "passed" if test_count is not None else "skipped",
        "live_api_calls": 0,
        "simulation_run_count": (
            matrix["run_count"] + replay["run_count"] + deadline["run_count"]
            + order["run_count"]
        ),
        "runs": {
            "event_matrix": matrix["run_count"],
            "recorded_proposal_replay": replay["run_count"],
            "deadline_sensitivity": deadline["run_count"],
            "proposal_order_sensitivity": order["run_count"],
        },
        "error_count": matrix["error_count"],
        "outputs": {
            "event_matrix": str(matrix_path.relative_to(ROOT.parent)),
            "recorded_proposal_replay": str(replay_path.relative_to(ROOT.parent)),
            "deadline_sensitivity": str(deadline_path.relative_to(ROOT.parent)),
            "proposal_order_sensitivity": str(order_path.relative_to(ROOT.parent)),
            "grounding_audit": str(audit_path.relative_to(ROOT.parent)),
            "episode_validity_audit": str(episode_validity_path.relative_to(ROOT.parent)),
            "external_goal_credit_audit": str(external_goal_credit_path.relative_to(ROOT.parent)),
            "deadline_feasibility_audit": str(deadline_feasibility_path.relative_to(ROOT.parent)),
            "baseline_coverage_audit": str(baseline_coverage_path.relative_to(ROOT.parent)),
        },
        "interpretation": (
            "Deterministic dry runs and offline replay only. No model API calls, "
            "no real concurrent API execution, and no device-calibrated physical parameters."
        ),
    }
    summary_path = RESULTS / "event_pilot_suite_20260926.json"
    summary["outputs"]["suite_summary"] = str(summary_path.relative_to(ROOT.parent))
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_suite(skip_tests=args.skip_tests), ensure_ascii=False, indent=2))
