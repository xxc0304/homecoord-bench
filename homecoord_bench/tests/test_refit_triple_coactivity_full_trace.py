import csv
import json
import tempfile
import unittest
from pathlib import Path

from homecoord_bench.extract_refit_triple_coactivity_full_trace import scan_trace


class RefitTripleCoactivityFullTraceTests(unittest.TestCase):
    def test_threshold_quality_gap_and_all_combinations(self):
        channels = ["Appliance1", "Appliance2", "Appliance3", "Appliance4"]
        rows = [
            (0, "0", [60, 60, 60, 0]),
            (8, "0", [120, 120, 120, 0]),
            (16, "1", [120, 120, 120, 0]),
            (24, "0", [120, 120, 120, 0]),
            (48, "0", [120, 120, 120, 0]),  # 24 s gap: closes and starts a new bout
            (56, "0", [120, 120, 20, 0]),  # threshold drop closes it
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Time", "Unix", "Issues", *channels])
                for timestamp, issues, values in rows:
                    writer.writerow([f"2026-01-01 00:00:{timestamp:02d}", timestamp, issues, *values])
            episodes = root / "episodes.csv"
            report_path = root / "report.json"
            report = scan_trace(
                source,
                episodes,
                report_path,
                channels=channels,
                thresholds=[50, 100],
                min_export_duration_seconds=0,
            )

            self.assertEqual(report["combinations_screened"], 4)
            self.assertEqual(report["trace_counts"]["rows"], 6)
            self.assertEqual(report["trace_counts"]["issues_1_rows"], 1)
            self.assertEqual(report["trace_counts"]["timestamp_gaps_over_limit"], 1)
            self.assertEqual(report["by_threshold"]["50"]["bout_count_across_triples"], 3)
            self.assertEqual(report["by_threshold"]["100"]["bout_count_across_triples"], 3)

            with episodes.open("r", encoding="utf-8-sig", newline="") as handle:
                got = list(csv.DictReader(handle))
            triple_123_100 = [
                row for row in got
                if row["threshold_w"] == "100" and row["channels"] == "Appliance1+Appliance2+Appliance3"
            ]
            self.assertEqual(len(triple_123_100), 3)
            self.assertEqual(triple_123_100[0]["boundary_after_status"], "Issues_nonzero")
            self.assertEqual(triple_123_100[1]["boundary_after_status"], "timestamp_gap_over_limit")
            self.assertEqual(triple_123_100[2]["boundary_before_status"], "timestamp_gap_over_limit")
            self.assertEqual(triple_123_100[2]["boundary_after_status"], "one_or_more_channels_below_threshold")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["channel_mapping"], "unverified; only raw Appliance channel labels are retained")


if __name__ == "__main__":
    unittest.main()
