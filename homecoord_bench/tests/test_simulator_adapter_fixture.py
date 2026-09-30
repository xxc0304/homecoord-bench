"""Offline checks for the project-authored HVAC adapter input fixture."""

import json
import unittest
from pathlib import Path


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "simulator_adapter"
    / "hvac_trial_inputs_v0.1.json"
)


class SimulatorAdapterFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_fixture_is_authored_adapter_input(self):
        self.assertEqual("homecoord_authored_configuration", self.fixture["source_type"])
        self.assertEqual("authored_homecoord_adapter_input_v0.1", self.fixture["status"])
        self.assertEqual(
            "83d28837b69f0cbf1bc02ed5334cb8b561a9d54d",
            self.fixture["backend"]["commit"],
        )

    def test_initial_thermostat_deadband_and_cooling_target_are_valid(self):
        attrs = self.fixture["reset_config"]["rooms"]["living_room"]["devices"][0]["attributes"]
        initial_heat = attrs["1.Thermostat.OccupiedHeatingSetpoint"]
        initial_cool = attrs["1.Thermostat.OccupiedCoolingSetpoint"]
        target_cool = next(
            step["args"]["value"]
            for step in self.fixture["proposal_command_bundles"]["cool"]["steps"]
            if step["tool"] == "write_attribute"
            and step["args"].get("attribute_id") == "OccupiedCoolingSetpoint"
        )
        self.assertGreaterEqual(initial_cool - initial_heat, 25)
        self.assertGreaterEqual(target_cool - initial_heat, 25)
        self.assertEqual(2900, self.fixture["reset_config"]["rooms"]["living_room"]["state"]["temperature"])

    def test_cool_is_one_four_step_proposal_and_off_is_one_command(self):
        cool_steps = self.fixture["proposal_command_bundles"]["cool"]["steps"]
        off_steps = self.fixture["proposal_command_bundles"]["off"]["steps"]
        self.assertEqual(4, len(cool_steps))
        self.assertEqual("On", cool_steps[0]["args"]["command_id"])
        self.assertEqual("SystemMode", cool_steps[1]["args"]["attribute_id"])
        self.assertEqual(3, cool_steps[1]["args"]["value"])
        self.assertEqual("OccupiedCoolingSetpoint", cool_steps[2]["args"]["attribute_id"])
        self.assertEqual("PercentSetting", cool_steps[3]["args"]["attribute_id"])
        self.assertEqual(1, len(off_steps))
        self.assertEqual("Off", off_steps[0]["args"]["command_id"])

    def test_order_pair_reverses_only_the_two_high_level_actions(self):
        schedules = self.fixture["paired_schedules"]
        self.assertEqual(["cool", "off"], schedules[0]["proposal_order"])
        self.assertEqual(["off", "cool"], schedules[1]["proposal_order"])
        self.assertEqual([20, 21], schedules[0]["proposal_start_offsets_seconds"])
        self.assertEqual(schedules[0]["proposal_start_offsets_seconds"], schedules[1]["proposal_start_offsets_seconds"])


if __name__ == "__main__":
    unittest.main()
