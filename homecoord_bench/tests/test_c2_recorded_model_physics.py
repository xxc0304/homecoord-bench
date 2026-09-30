"""Checks for the C2 recorded-proposal to continuous-physics boundary."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c2_recorded_model_physics import classify, make_request, replay_row
from probe_ventilation_heating_tradeoff import simulate
from evaluate import ROOT


class C2RecordedModelPhysicsTests(unittest.TestCase):
    def test_matched_air_requests_change_only_co2_and_identity(self):
        high = make_request("conflict", "air", 1)
        low = make_request("control", "air", 1)
        self.assertEqual(high["state"]["bedroom"]["co2_ppm"], 1600)
        self.assertEqual(low["state"]["bedroom"]["co2_ppm"], 850)
        self.assertEqual(high["task"], low["task"])
        self.assertEqual(high["available_actions"], low["available_actions"])
        self.assertNotIn("temperature_c", high["state"]["bedroom"])

    def test_delayed_proposal_cannot_start_physical_action_early(self):
        args = dict(initial_co2_ppm=1600, ventilation_rate_ppm_s=2.5,
                    open_exchange_per_s=0.0015, deadline_ms=360000)
        normal = simulate(**args, policy="Independent")
        delayed = simulate(**args, policy="Independent",
                           air_proposal_ready_ms=12_300,
                           heat_proposal_ready_ms=14_200)
        self.assertEqual(delayed["window_open_command_ms"], 13_000)
        self.assertEqual(delayed["heater_first_start_ms"], 15_000)
        self.assertGreater(delayed["goal_completion_ms"], normal["goal_completion_ms"])

    def test_recorded_decisions_are_reused_across_conditions_and_policies(self):
        source = ROOT / "results" / "c2_recorded_model_physics_20260928.json"
        if not source.exists():
            self.skipTest("recorded model probe has not been run")
        row = json.loads(source.read_text(encoding="utf-8"))["rows"][0]
        self.assertEqual(classify(row["model_records"]["air_conflict"], "air"),
                         "expected_action")
        self.assertEqual(classify(row["model_records"]["air_control"], "air"),
                         "no_action")
        self.assertEqual(classify(row["model_records"]["heat_shared"], "heat"),
                         "expected_action")
        replay = replay_row(row)
        self.assertEqual(len(replay), 20)
        self.assertEqual({item["heat_model_latency_ms"] for item in replay},
                         {row["model_records"]["heat_shared"]["logical_latency_ms"]})
        self.assertTrue(all(item["deadline_met"] for item in replay
                            if item["condition"] == "control"))


if __name__ == "__main__":
    unittest.main()
