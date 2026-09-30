"""Guard the paired-record protocol used for exploratory cross-task replay."""

from __future__ import annotations

import json
import unittest

from evaluate import ROOT
from replay_cross_task_recorded_proposals import _episode_and_records, run


class CrossTaskRecordedReplayTests(unittest.TestCase):
    def test_pair_preserves_task_order_and_condition_specific_record(self) -> None:
        payload = json.loads((ROOT / "results" / "paired_task_batch_v1_probe.json").read_text(
            encoding="utf-8"
        ))
        row = next(item for item in payload["rows"] if item["pair_id"] == "C1-BLINDS")
        conflict, conflict_records = _episode_and_records("C1-BLINDS", "conflict", row)
        control, control_records = _episode_and_records("C1-BLINDS", "control", row)
        self.assertEqual(conflict_records[0], row["model_records"]["first_conflict"])
        self.assertEqual(control_records[0], row["model_records"]["first_control"])
        self.assertEqual(conflict_records[1], control_records[1])
        self.assertEqual(len(conflict_records), len(conflict["task_stream"]))
        self.assertEqual(len(control_records), len(control["task_stream"]))

    def test_policies_share_model_arrivals_and_safety_gate(self) -> None:
        rows = run()["rows"]
        self.assertEqual(len(rows), 150)
        for pair in {row["pair_id"] for row in rows}:
            for condition in ("conflict", "control"):
                for repetition in range(1, 6):
                    group = [row for row in rows if row["pair_id"] == pair
                             and row["condition"] == condition
                             and row["source_repetition"] == repetition]
                    self.assertEqual(len(group), 5)
                    self.assertEqual(len({json.dumps(row["model_latency_by_task_ms"], sort_keys=True)
                                          for row in group}), 1)
                    self.assertEqual(len({json.dumps(row["proposal_response_type_by_task"], sort_keys=True)
                                          for row in group}), 1)


if __name__ == "__main__":
    unittest.main()
