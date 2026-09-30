"""Check the review-only C1/C3 data pack before anyone interprets its results."""

import sys
import unittest
import hashlib
import json
from copy import deepcopy
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from generate_provenance_pilot import OUT, build  # noqa: E402
from runtime.dry_run import DryRunClient  # noqa: E402
from runtime.episode_validation import validate_event_episode  # noqa: E402
from runtime.event_simulator import run_event_simulation  # noqa: E402
from runtime.protocol import build_agent_request  # noqa: E402


class ProvenancePilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episodes = {episode["episode_id"]: episode for episode in build()}

    def test_episode_contract_and_provenance(self):
        self.assertEqual(5, len(self.episodes))
        for episode in self.episodes.values():
            self.assertEqual([], validate_event_episode(episode), episode["episode_id"])
            self.assertEqual("mechanism_only", episode["data_tier"])
            self.assertEqual("provenance_pilot_unreviewed_not_scored", episode["review_status"])
            self.assertFalse(episode["calibration"]["physical_parameters_verified"])
            self.assertTrue(episode["parameter_provenance"])
            agents = {agent["agent_id"]: agent for agent in episode["agents"]}
            for task in episode["task_stream"]:
                request = build_agent_request(
                    episode, agents[task["agent_id"]], task,
                    architecture="IndependentMultiAgent",
                    current_time_ms=task["release_at_ms"],
                    current_state=episode["initial_state"]["values"],
                    state_version=episode["initial_state"]["version"],
                )
                self.assertNotIn("action_template", request["task"])
                self.assertNotIn("required_action", request["task"])

    def test_written_manifest_hashes_match_exact_files(self):
        manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["episode_sha256"]),
                         {f"{episode_id}.json" for episode_id in self.episodes})
        for name, digest in manifest["episode_sha256"].items():
            self.assertEqual(digest, hashlib.sha256((OUT / name).read_bytes()).hexdigest())

    def test_c1_does_not_turn_a_setpoint_into_room_temperature(self):
        for condition in ("OVERLAP", "NONOVERLAP"):
            episode = self.episodes[f"HC-PROV-C1-{condition}"]
            self.assertTrue(all("temperature_c" not in goal["path"] for goal in episode["goals"]))
            self.assertTrue(all(
                "living_room.temperature_c" not in effect
                for action in episode["action_grounding"]
                for effect in (action.get("start_effects", {}), action.get("completion_effects", {}))
            ))
            cooling = next(action for action in episode["action_grounding"]
                           if action["operation"] == "cool")
            self.assertEqual({}, cooling["completion_effects"])
            self.assertEqual({"request.comfort_active": False},
                             episode["exogenous_events"][0]["patch"])
            energy_agent = next(agent for agent in episode["agents"]
                                if agent["agent_id"] == "EnergyAgent")
            energy_task = next(task for task in episode["task_stream"]
                               if task["agent_id"] == "EnergyAgent")
            energy_request = build_agent_request(
                episode, energy_agent, energy_task,
                architecture="IndependentMultiAgent",
                current_time_ms=energy_task["release_at_ms"],
                current_state=episode["initial_state"]["values"],
                state_version=episode["initial_state"]["version"],
            )
            self.assertNotIn("request", energy_request["state"])
            self.assertEqual([], energy_request["goals"])
            self.assertEqual([], energy_request["constraints"])
            _, outcome = run_event_simulation(episode, DryRunClient(), "ConstraintCoordinator", "")
            self.assertTrue(outcome["process_valid_success"])

        _, premature_off = run_event_simulation(
            self.episodes["HC-PROV-C1-OVERLAP"], DryRunClient(), "IndependentMultiAgent", ""
        )
        self.assertTrue(premature_off["final_goal_success"])
        self.assertFalse(premature_off["process_valid_success"])
        self.assertGreater(premature_off["state_constraint_violation_duration_ms"], 0)

        overlap = deepcopy(self.episodes["HC-PROV-C1-OVERLAP"])
        nonoverlap = deepcopy(self.episodes["HC-PROV-C1-NONOVERLAP"])
        for item in (overlap, nonoverlap):
            item.pop("episode_id")
            item["variant"].pop("condition")
            next(task for task in item["task_stream"] if task["task_id"] == "peak_off").pop("release_at_ms")
            item["parameter_provenance"].pop("energy_task_release_at_ms")
        self.assertEqual(overlap, nonoverlap)

    def test_c3_changes_only_capacity_and_exposes_unsourced_budget(self):
        c3 = [self.episodes[f"HC-PROV-C3-{condition}"]
              for condition in ("BELOW", "EQUAL", "ABOVE")]
        self.assertEqual([7.0, 7.8, 9.0],
                         [e["home"]["resources"]["max_power_kw"] for e in c3])
        for episode in c3:
            self.assertEqual("assumed_managed_load_budget",
                             episode["home"]["resources"]["capacity_scope"])
            self.assertEqual("controlled_experimental_factor_no_home_record",
                             episode["parameter_provenance"]["managed_load_budget_kw"]["class"])
            self.assertTrue(all("completion_deadline_ms" not in t for t in episode["task_stream"]))
            self.assertAlmostEqual(7.8, sum(
                action["power_kw"] for action in episode["action_grounding"]
                if action["operation"] in ("charge", "heat")
            ))
        def without_factor(source):
            item = deepcopy(source)
            item.pop("episode_id")
            item["variant"].pop("condition")
            item["home"]["resources"].pop("max_power_kw")
            item["conflict_rules"][0].pop("capacity")
            item["parameter_provenance"].pop("managed_load_budget_kw")
            return item

        baseline = without_factor(c3[0])
        for episode in c3[1:]:
            self.assertEqual(baseline, without_factor(episode))

    def test_controlled_mechanism_and_feasibility(self):
        for episode in self.episodes.values():
            _, coordinated = run_event_simulation(
                episode, DryRunClient(), "ConstraintCoordinator", ""
            )
            self.assertTrue(coordinated["process_valid_success"], episode["episode_id"])
            self.assertEqual(1.0, coordinated["task_service_rate"], episode["episode_id"])
        expected = {"HC-PROV-C1-OVERLAP": "C1", "HC-PROV-C3-BELOW": "C3"}
        for episode_id, family in expected.items():
            _, independent = run_event_simulation(
                self.episodes[episode_id], DryRunClient(), "IndependentMultiAgent", ""
            )
            self.assertEqual(1, independent["conflict_counts"][family])
        for episode_id in ("HC-PROV-C1-NONOVERLAP", "HC-PROV-C3-EQUAL", "HC-PROV-C3-ABOVE"):
            _, independent = run_event_simulation(
                self.episodes[episode_id], DryRunClient(), "IndependentMultiAgent", ""
            )
            self.assertTrue(independent["process_valid_success"], episode_id)


if __name__ == "__main__":
    unittest.main()
