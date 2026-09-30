"""Prevent cross-house REFIT analyses from inheriting House 5 identifiers."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract_refit_coactivity_windows import extract_windows  # noqa: E402
from extract_refit_triple_coactivity_bouts import extract_bouts  # noqa: E402


class RefitCoactivityHouseIdTests(unittest.TestCase):
    def test_pair_window_id_uses_requested_house(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "house1.csv"
            source.write_text(
                "Time,Unix,Issues,Appliance4,Appliance5,Appliance6\n"
                "2013-10-09 00:00:00,1000,0,0,120,130\n"
                "2013-10-09 00:00:08,1008,0,0,140,150\n",
                encoding="utf-8",
            )
            report = extract_windows(
                source,
                start_date_inclusive=date(2013, 10, 9),
                end_date_exclusive=date(2013, 10, 10),
                threshold_w=100,
                max_gap_seconds=16,
                device_columns={"dryer": "Appliance4", "washer": "Appliance5", "dishwasher": "Appliance6"},
                house_id="H1",
            )
        self.assertEqual("REFIT-H1", report["house_id"])
        self.assertEqual("REFIT-H1-COACT-000001", report["windows"][0]["window_id"])

    def test_triple_bout_uses_supplied_channels_and_house(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.csv"
            context = root / "context.csv"
            output = root / "bouts.csv"
            rows_output = root / "rows.csv"
            report_path = root / "report.json"
            summary.write_text("review_window_id\nREFIT-H1-COACT-000001\n", encoding="utf-8")
            fields = [
                "review_window_id", "device_pair", "row_relation", "source_csv_line", "Time", "Unix",
                "Aggregate", "Appliance4", "Appliance5", "Appliance6", "Issues",
            ]
            rows = [
                ["REFIT-H1-COACT-000001", "washer+dishwasher", "context_before", 1, "t0", 1000, 0, 0, 0, 0, 0],
                ["REFIT-H1-COACT-000001", "washer+dishwasher", "candidate_window", 2, "t1", 1008, 600, 100, 200, 300, 0],
                ["REFIT-H1-COACT-000001", "washer+dishwasher", "candidate_window", 3, "t2", 1016, 650, 150, 210, 310, 0],
                ["REFIT-H1-COACT-000001", "washer+dishwasher", "context_after", 4, "t3", 1024, 0, 0, 0, 0, 0],
            ]
            with context.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(fields)
                writer.writerows(rows)

            report = extract_bouts(
                summary,
                context,
                output,
                rows_output,
                report_path,
                channels=["Appliance4", "Appliance5", "Appliance6"],
                house_id="H1",
                threshold_w=100,
                max_gap_seconds=16,
            )
            saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(1, report["bout_count"])
        self.assertEqual("REFIT-H1-TRIPLE-100W-001", report["bouts"][0]["bout_id"])
        self.assertEqual(["Appliance4", "Appliance5", "Appliance6"], saved["channels"])


if __name__ == "__main__":
    unittest.main()
