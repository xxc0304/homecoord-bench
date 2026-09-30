"""Checks for the C3 non-nested parameter provenance matrix."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_c3_non_nested_provenance import audit


class C3NonNestedProvenanceTests(unittest.TestCase):
    def test_matrix_matches_executable_templates_and_declares_gaps(self):
        report = audit(output=None)
        self.assertEqual("pass_with_declared_gaps", report["status"])
        self.assertEqual(7, report["record_count"])
        self.assertEqual(7, report["exact_e2_power_count"])
        self.assertEqual(1, report["exact_e2_duration_count"])
        self.assertEqual([], report["errors"])
        self.assertFalse(any(row["field"] == "power_kw" for row in report["unresolved"]))


if __name__ == "__main__":
    unittest.main()
