import sys
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import load_json  # noqa: E402
from probe_information_boundary_20260926 import classify, replay_active, request  # noqa: E402


def decision(operation):
    return {
        "actions": [] if operation is None else [{
            "proposal_id": operation, "target": "living_hvac", "operation": operation,
            "parameters": [], "based_on_state_version": 200, "requires": [],
            "estimated_duration_ms": None, "estimated_power_kw": None,
        }]
    }


class InformationBoundaryProbeTests(unittest.TestCase):
    def test_model_input_excludes_evaluator_answer_and_future_proposals(self):
        for fact, policy in ((False, False), (True, False), (False, True), (True, True)):
            item = request("EnergyAgent", active=True, fact=fact, policy=policy)
            self.assertNotIn("required_action", item["task"])
            self.assertNotIn("goals", item)
            self.assertEqual([], item["pending_proposals"])
            self.assertEqual(fact, "request" in item["state"])
            self.assertEqual(policy, bool(item["constraints"]))

    def test_forced_off_tool_alias_counts_as_off(self):
        item = decision("set_hvac")
        item["actions"][0]["parameters"] = [{"name": "mode", "value": "forced_off"}]
        self.assertEqual("off", classify(item))

    def test_same_proposal_online_gate_removes_conflict_but_loses_energy_service(self):
        episode = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-002.json")
        episode["initial_state"]["values"]["devices"]["living_hvac"] = "cool_26"
        replay = replay_active(episode, decision("cool"), decision("off"))
        self.assertFalse(replay["independent"]["process_valid_success"])
        self.assertEqual(1, replay["independent"]["C1"])
        self.assertTrue(replay["online_gate"]["process_valid_success"])
        self.assertFalse(replay["online_gate"]["task_service"]["energy"])
        safe = replay_active(episode, decision("cool"), decision(None))
        self.assertTrue(safe["independent"]["process_valid_success"])
        self.assertEqual(0, safe["independent"]["C1"])

        guarded = decision("off")
        guarded["actions"][0]["requires"] = [{
            "path": "request.comfort_active", "op": "eq", "value": False,
            "range_min": None, "range_max": None,
        }]
        guarded_replay = replay_active(episode, decision("cool"), guarded)
        self.assertTrue(guarded_replay["independent"]["process_valid_success"])
        self.assertEqual(1, guarded_replay["independent"]["precondition_rejections"])


if __name__ == "__main__":
    unittest.main()
