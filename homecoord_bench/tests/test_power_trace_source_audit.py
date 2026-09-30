"""Guard the boundary between observed power data and invented task fields."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from homecoord_bench.inspect_power_trace_csv import inspect_csv


class PowerTraceSourceAuditTest(unittest.TestCase):
    def test_observational_summary_and_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "trace.csv"
            source.write_text(
                "timestamp,washer,dishwasher\n"
                "100,0,0\n101,1200,NA\n102,1100,800\n110,0,850\n",
                encoding="utf-8",
            )
            report = inspect_csv(
                source,
                timestamp_column="timestamp",
                device_columns={"washer": "washer", "dishwasher": "dishwasher"},
                expected_interval_seconds=1,
                source_url="https://example.org/public-trace",
                house_id="test-house",
            )
        self.assertEqual(report["rows"], 4)
        self.assertEqual(report["timestamp_gap_count_over_2x_cadence"], 1)
        self.assertEqual(report["largest_timestamp_gap_seconds"], 8)
        self.assertEqual(report["devices"]["dishwasher"]["valid_fraction"], 0.75)
        self.assertEqual(report["devices"]["washer"]["observed_max_w"], 1200)
        self.assertNotIn("hard_deadlines", report)
        self.assertIn("user deadlines or urgency", report["not_inferred"])

    def test_rejects_unordered_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "trace.csv"
            source.write_text("t,p\n100,0\n100,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-monotonic"):
                inspect_csv(
                    source,
                    timestamp_column="t",
                    device_columns={"device": "p"},
                    expected_interval_seconds=1,
                    source_url="https://example.org/public-trace",
                    house_id="test-house",
                )

    def test_rejects_wrong_device_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "trace.csv"
            source.write_text("t,p\n100,0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing columns"):
                inspect_csv(
                    source,
                    timestamp_column="t",
                    device_columns={"washer": "q"},
                    expected_interval_seconds=1,
                    source_url="https://example.org/public-trace",
                    house_id="test-house",
                )

    def test_requires_and_counts_refit_issue_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "trace.csv"
            source.write_text(
                "Unix,Appliance2,Issues\n"
                "100,0,0\n101,1200,1\n102,900,0\n103,0,unknown\n",
                encoding="utf-8",
            )
            kwargs = dict(
                timestamp_column="Unix",
                device_columns={"dryer": "Appliance2"},
                expected_interval_seconds=1,
                source_url="https://example.org/public-trace",
                house_id="test-house",
            )
            with self.assertRaisesRegex(ValueError, "pass quality_flag_column"):
                inspect_csv(source, **kwargs)
            report = inspect_csv(source, quality_flag_column="Issues", **kwargs)
        self.assertEqual(report["quality_flags"]["clear_rows"], 2)
        self.assertEqual(report["quality_flags"]["flagged_rows"], 1)
        self.assertEqual(report["quality_flags"]["invalid_or_missing_rows"], 1)
        self.assertEqual(report["quality_flags"]["flagged_fraction"], 0.25)


if __name__ == "__main__":
    unittest.main()
