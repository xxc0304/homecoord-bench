"""Causal control checks for the synthetic model-error probe."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_ventilation_heating_model_error import evaluate_estimate  # noqa: E402


class VentilationHeatingModelErrorTests(unittest.TestCase):
    def test_exact_model_agrees_with_oracle(self):
        for deadline in (240000, 360000, 480000):
            row = evaluate_estimate(initial_co2_ppm=1600, true_rate=2.5,
                                    true_exchange=0.0015, estimated_rate=2.5,
                                    estimated_exchange=0.0015, deadline_ms=deadline)
            self.assertEqual(row["actual_selected_on_time"], row["actual_oracle_on_time"])
            self.assertFalse(row["avoidable_deadline_miss"])
            if row["actual_selected_on_time"]:
                self.assertEqual(row["avoidable_extra_energy_wh"], 0)

    def test_optimistic_rate_can_cause_avoidable_miss(self):
        row = evaluate_estimate(initial_co2_ppm=1600, true_rate=2.5,
                                true_exchange=0.0005, estimated_rate=5.0,
                                estimated_exchange=0.0005, deadline_ms=360000)
        self.assertEqual(row["selected_policy"], "StateGate")
        self.assertTrue(row["avoidable_deadline_miss"])

    def test_no_ventilation_control_is_insensitive_to_estimate(self):
        row = evaluate_estimate(initial_co2_ppm=850, true_rate=2.5,
                                true_exchange=0.003, estimated_rate=5.0,
                                estimated_exchange=0.0005, deadline_ms=360000)
        self.assertFalse(row["avoidable_deadline_miss"])
        self.assertEqual(row["avoidable_extra_energy_wh"], 0)


if __name__ == "__main__":
    unittest.main()
