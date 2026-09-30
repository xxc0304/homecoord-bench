"""The retry rule must reuse one proposal and preserve the common safety floor."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c3_gate_retry_baseline import SOURCE, run
from probe_c3_non_nested_templates import TEMPLATES
from probe_c3_structural_generalization import make_episode_from_specs
from probe_c3_three_load import ScriptedProposalClient
from runtime.event_simulator import run_event_simulation


class C3GateRetryBaselineTests(unittest.TestCase):
    def test_retry_requires_shared_safety_gate(self):
        episode = make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2)
        with self.assertRaisesRegex(ValueError, "requires the shared safety gate"):
            run_event_simulation(episode, ScriptedProposalClient({}), "GateRetryRule", "")

    def test_rejected_proposal_is_retried_without_new_model_call(self):
        episode = make_episode_from_specs("KITCHEN_CIRCUIT", TEMPLATES["KITCHEN_CIRCUIT"], 1.2)
        latencies = {task["task_id"]: 1000 + index * 100
                     for index, task in enumerate(episode["task_stream"])}
        trace, result = run_event_simulation(
            episode, ScriptedProposalClient(latencies), "GateRetryRule", "",
            shared_safety_gate=True,
        )
        self.assertEqual(3, result["proposal_count"])
        self.assertGreater(result["retry_queued_count"], 0)
        self.assertEqual(result["retry_queued_count"], result["retry_scheduled_count"])
        self.assertEqual(3, result["accepted_action_count"])
        self.assertTrue(result["all_deadlines_met"])
        self.assertEqual(3, len({event["proposal_id"] for event in trace["events"]
                                 if event["type"] == "action_started"}))

    def test_saved_batch_pairing(self):
        if not SOURCE.exists():
            self.skipTest("saved live proposal pilot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            report = run(output=Path(directory) / "result.json")
        self.assertEqual(18, report["new_replays"])
        self.assertEqual(90, len(report["rows"]))


if __name__ == "__main__":
    unittest.main()
