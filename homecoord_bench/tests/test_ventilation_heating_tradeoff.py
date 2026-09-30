"""Invariant checks for the standalone HC-M06 thermal design probe."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_ventilation_heating_tradeoff import simulate


class VentilationHeatingTradeoffTests(unittest.TestCase):
    def test_no_ventilation_control_has_no_policy_penalty(self):
        rows = [simulate(initial_co2_ppm=850, ventilation_rate_ppm_s=2.5,
                         open_exchange_per_s=0.0015, deadline_ms=360000,
                         policy=policy)
                for policy in ("Independent", "DeviceLock", "ActionOverlapLock", "StateGate", "OracleSwitch")]
        self.assertEqual({row["goal_completion_ms"] for row in rows}, {168000})
        self.assertEqual(len({row["heater_energy_wh"] for row in rows}), 1)
        self.assertTrue(all(row["window_open_heater_ms"] == 0 for row in rows))

    def test_conflict_has_valid_physical_endpoints_and_tradeoff(self):
        args = dict(initial_co2_ppm=1600, ventilation_rate_ppm_s=2.5,
                    open_exchange_per_s=0.0015, deadline_ms=360000)
        independent = simulate(**args, policy="Independent")
        gate = simulate(**args, policy="StateGate")
        for row in (independent, gate):
            self.assertIsNotNone(row["window_close_ms"])
            self.assertLessEqual(row["final_co2_ppm"], 900)
            self.assertGreaterEqual(row["final_temp_c"], 21)
        self.assertTrue(independent["deadline_met"])
        self.assertFalse(gate["deadline_met"])
        self.assertGreater(independent["heater_energy_wh"], gate["heater_energy_wh"])
        self.assertGreater(independent["window_open_heater_ms"], 0)
        self.assertEqual(gate["window_open_heater_ms"], 0)

    def test_faster_ventilation_closes_window_earlier(self):
        args = dict(initial_co2_ppm=1600, open_exchange_per_s=0.0015,
                    deadline_ms=480000, policy="StateGate")
        slow = simulate(**args, ventilation_rate_ppm_s=2.5)
        fast = simulate(**args, ventilation_rate_ppm_s=5.0)
        self.assertLess(fast["window_close_ms"], slow["window_close_ms"])

    def test_perfect_information_switch_exposes_simple_solution(self):
        args = dict(initial_co2_ppm=1600, ventilation_rate_ppm_s=2.5,
                    open_exchange_per_s=0.0015, deadline_ms=360000)
        oracle = simulate(**args, policy="OracleSwitch")
        independent = simulate(**args, policy="Independent")
        self.assertEqual(oracle["selected_policy"], "Independent")
        self.assertEqual(oracle["goal_completion_ms"], independent["goal_completion_ms"])


if __name__ == "__main__":
    unittest.main()
