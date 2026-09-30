"""Checks for the measured-trace compatibility audit of the C2 model."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_c2_observational_compatibility import run


class C2ObservationalCompatibilityTests(unittest.TestCase):
    def test_two_units_do_not_calibrate_current_synthetic_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run(Path(directory) / "audit.json")
        summary = report["summary"]
        self.assertEqual(summary["independent_units"], 2)
        self.assertEqual(summary["selected_windows"], 6)
        self.assertGreater(summary["usable_multi_bin_open_windows"], 0)
        self.assertEqual(summary["high_co2_windows_by_file"]["49643061"], 0)
        self.assertEqual(summary["co2_rates_inside_current_synthetic_range"], 0)
        self.assertIn("Do not promote", summary["decision"])


if __name__ == "__main__":
    unittest.main()
