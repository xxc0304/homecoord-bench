"""Checks causal message timing and the robot stop/restart contract."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_c4_agent_message import (
    classify_control, execute, reported_occupied_at_exit, replay_row,
)


def report(operation, latency):
    return {"logical_latency_ms": latency, "decision": {
        "response_type": "action_proposal", "actions": [{
            "target": "occupancy_channel", "operation": operation, "parameters": [],
        }]}}


class C4AgentMessageTests(unittest.TestCase):
    def test_early_message_stops_and_clear_report_restarts(self):
        entry = report("report_occupied", 500)
        clear = report("report_clear", 500)
        stop = execute(1400, entry, clear, condition="conflict",
                       policy="AgentMessageStopOnly")
        retry = execute(1400, entry, clear, condition="conflict",
                        policy="AgentMessageStopRestart")
        self.assertEqual(stop["unsafe_overlap_duration_ms"], 800)
        self.assertFalse(stop["clean_task_served"])
        self.assertEqual(retry["unsafe_overlap_duration_ms"], 800)
        self.assertEqual(retry["clean_completion_ms"], 8700)

    def test_late_message_cannot_cancel_completed_cleaning(self):
        late = execute(1400, report("report_occupied", 1400),
                       report("report_clear", 500), condition="conflict",
                       policy="AgentMessageStopRestart")
        direct = execute(1400, None, None, condition="conflict",
                         policy="DirectSensorStopRestart")
        self.assertIsNone(late["stop_ack_at_ms"])
        self.assertEqual(late["unsafe_overlap_duration_ms"], 1500)
        self.assertEqual(direct["unsafe_overlap_duration_ms"], 200)
        self.assertEqual(direct["clean_completion_ms"], 8100)

    def test_exit_observes_only_previously_delivered_entry_report(self):
        self.assertTrue(reported_occupied_at_exit(report("report_occupied", 1800)))
        self.assertFalse(reported_occupied_at_exit(report("report_occupied", 1901)))
        self.assertFalse(reported_occupied_at_exit(report("report_clear", 500)))

    def test_no_event_false_positive_can_cause_service_loss(self):
        false_positive = report("report_occupied", 500)
        self.assertEqual(classify_control(false_positive), "false_occupied_report")
        harmful = execute(1400, false_positive, None, condition="control",
                          policy="AgentMessageStopRestart")
        correct = execute(1400, report("report_clear", 500), None,
                          condition="control", policy="AgentMessageStopRestart")
        self.assertFalse(harmful["clean_task_served"])
        self.assertTrue(correct["clean_task_served"])
        self.assertEqual(classify_control(report("report_clear", 500)),
                         "redundant_clear_report")

    def test_replay_reuses_one_clean_proposal_across_all_arms(self):
        row = {"repetition": 1, "model_records": {
            "entry_conflict": report("report_occupied", 500),
            "exit_conflict": report("report_clear", 500),
            "check_control": report("report_clear", 500),
        }}
        clean = {"model_records": {"bedroom_clean": {
            "logical_latency_ms": 1400,
            "decision": {"response_type": "action_proposal", "actions": [{
                "target": "bedroom_robot", "operation": "clean",
            }]},
        }}}
        results = replay_row(row, clean)
        self.assertEqual(len(results), 8)
        self.assertEqual({x["clean_model_latency_ms"] for x in results}, {1400})
        self.assertEqual({x["clean_first_start_ms"] for x in results}, {1500})


if __name__ == "__main__":
    unittest.main()
