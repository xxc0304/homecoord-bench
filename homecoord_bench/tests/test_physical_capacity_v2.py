"""Verify completion-event semantics and paired capacity controls."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_physical_capacity_v2 import make_episode, physical_work_ms, schedule
from runtime.protocol import build_agent_request


def record(target, operation, name, value, latency_ms):
    return {
        "logical_latency_ms": latency_ms,
        "decision": {"actions": [{
            "target": target, "operation": operation,
            "parameters": [{"name": name, "value": value}],
        }]},
    }


class PhysicalCapacityTests(unittest.TestCase):
    def setUp(self):
        self.records = {
            "charge_ev": record("ev_charger", "charge", "target_battery_pct", 50, 1000),
            "heat_water": record("water_heater", "heat", "target_temperature_c", 50, 500),
        }

    def test_energy_accounting_uses_hours_not_seconds(self):
        durations = physical_work_ms()
        self.assertEqual(durations["charge_ev"], 18_000_000)
        self.assertGreater(durations["heat_water"], 2_000_000)

    def test_low_capacity_ordering_and_high_capacity_control(self):
        conflict = make_episode("conflict")
        control = make_episode("control")
        fifo = schedule(conflict, self.records, "ImmediateFIFO")
        priority = schedule(conflict, self.records, "WaitReleasedPriorityCapacityAware")
        high = schedule(control, self.records, "WaitReleasedPriorityCapacityAware")
        self.assertTrue(all(x["safe"] and x["all_tasks_completed"] for x in (fifo, priority, high)))
        self.assertFalse(fifo["ev_deadline_met"])
        self.assertTrue(priority["ev_deadline_met"])
        self.assertTrue(high["ev_deadline_met"])
        self.assertTrue(priority["water_deadline_met"])
        self.assertFalse(high["waited_for_urgent"])
        self.assertEqual(
            {x["task_id"] for x in priority["events"] if x["finish_ms"] <= 5000}, set()
        )

    def test_public_model_request_hides_template(self):
        episode = make_episode("conflict")
        for agent, task in zip(episode["agents"], episode["task_stream"]):
            request = build_agent_request(
                episode, agent, task, architecture="IndependentMultiAgent",
                current_time_ms=task["release_at_ms"],
            )
            self.assertNotIn("required_action", request["task"])
            self.assertNotIn("action_template", request["task"])
            self.assertEqual(len(request["available_actions"]), 2)

    def test_running_and_completed_device_states_are_separate(self):
        episode = make_episode("conflict")
        by_action = {(item["task_id"], item["operation"]): item for item in episode["action_grounding"]}
        self.assertEqual({"devices.ev_charger": "charging"}, by_action[("charge_ev", "charge")]["start_effects"])
        self.assertEqual(50, by_action[("charge_ev", "charge")]["completion_effects"]["vehicle.battery_pct"])
        self.assertEqual({"devices.water_heater": "heating"}, by_action[("heat_water", "heat")]["start_effects"])
        self.assertEqual(50, by_action[("heat_water", "heat")]["completion_effects"]["water.temperature_c"])


if __name__ == "__main__":
    unittest.main()
