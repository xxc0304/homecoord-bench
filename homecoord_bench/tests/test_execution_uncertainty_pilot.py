import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from probe_execution_uncertainty import simulate  # noqa: E402


class ExecutionUncertaintyPilotTests(unittest.TestCase):
    def test_command_ack_does_not_establish_physical_closure(self):
        optimistic = simulate(close_at_ms=600, status_lag_ms=100, policy="AckOptimistic")
        verified = simulate(close_at_ms=600, status_lag_ms=100, policy="PassiveConfirmation")
        self.assertFalse(optimistic["physically_valid"])
        self.assertEqual(100, optimistic["cooling_started_ms"])
        self.assertTrue(verified["on_time_valid"])
        self.assertEqual(700, verified["cooling_started_ms"])

    def test_query_resolves_sensor_lag_but_does_not_invent_success(self):
        passive = simulate(close_at_ms=1000, status_lag_ms=500, policy="PassiveConfirmation")
        active = simulate(close_at_ms=1000, status_lag_ms=500, policy="ActiveStatusQuery")
        failed = simulate(close_at_ms=None, status_lag_ms=500, policy="ActiveStatusQuery")
        self.assertFalse(passive["on_time_valid"])
        self.assertTrue(active["on_time_valid"])
        self.assertGreater(active["query_count"], 1)
        self.assertIsNone(failed["cooling_started_ms"])
        self.assertTrue(failed["physically_valid"])


if __name__ == "__main__":
    unittest.main()
