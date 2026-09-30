import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from probe_dynamic_repair import run, simulate  # noqa: E402


class DynamicRepairPilotTests(unittest.TestCase):
    def test_rain_requires_alternative_but_simple_reactive_rule_suffices(self):
        blocked = simulate("rain_mid", 3000, None, "StateGate")
        reactive = simulate("rain_mid", 3000, None, "ReactiveFallback")
        self.assertTrue(blocked["process_valid"])
        self.assertFalse(blocked["valid_on_time"])
        self.assertGreater(blocked["final_co2_ppm"], 900)
        self.assertTrue(reactive["valid_on_time"])
        self.assertEqual(0, reactive["cooling_while_open_ms"])
        self.assertEqual(1, sum(event["type"] == "cleaning_started" for event in reactive["events"]))

    def test_unrelated_event_does_not_trigger_repair_or_delay(self):
        with TemporaryDirectory() as directory:
            rows = run(Path(directory) / "result.json")["rows"]
        normal = {row["policy"]: row for row in rows if row["scenario"] == "no_event"}
        unrelated = {row["policy"]: row for row in rows if row["scenario"] == "unrelated_event"}
        for policy in normal:
            self.assertEqual(normal[policy]["goal_completion_ms"], unrelated[policy]["goal_completion_ms"])
            self.assertEqual(0, unrelated[policy]["repair_scope_count"])

    def test_replan_templates_have_same_physical_result(self):
        full = simulate("rain_early", 1500, None, "GlobalReplanTemplate")
        local = simulate("rain_early", 1500, None, "LocalRepairTemplate")
        self.assertEqual(full["goal_completion_ms"], local["goal_completion_ms"])
        self.assertGreater(full["repair_scope_count"], local["repair_scope_count"])


if __name__ == "__main__":
    unittest.main()
