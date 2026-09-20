import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_ROOT))

from evaluate import load_json  # noqa: E402
from run_protocol_pilot import run  # noqa: E402
from runtime.event_log import EventLogger  # noqa: E402
from runtime.deepseek_client import DeepSeekResponsesClient  # noqa: E402
from runtime.openai_client import OpenAIResponsesClient  # noqa: E402
from runtime.protocol import AGENT_DECISION_SCHEMA, build_agent_request, validate_agent_decision  # noqa: E402


def valid_decision():
    return {
        "response_type": "action_proposal",
        "actions": [{
            "proposal_id": "p1",
            "target": "study_light",
            "operation": "set_reading",
            "parameters": [{"name": "lux", "value": 500}],
            "based_on_state_version": 100,
            "requires": [],
            "estimated_duration_ms": 1000,
            "estimated_power_kw": 0.02,
        }],
        "accepted_proposal_ids": [],
        "rejected_proposal_ids": [],
        "defer_until_ms": None,
        "reason_code": "goal_progress",
    }


class RuntimeTests(unittest.TestCase):
    def seed_request(self):
        episode = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-001.json")
        return build_agent_request(
            episode,
            episode["agents"][0],
            episode["task_stream"][0],
            architecture="IndependentMultiAgent",
            current_time_ms=0,
        )

    def test_structured_output_schema_uses_strict_object_shapes(self):
        def visit(schema):
            if isinstance(schema, dict):
                if schema.get("type") == "object":
                    self.assertFalse(schema.get("additionalProperties", True))
                    self.assertEqual(set(schema["properties"]), set(schema["required"]))
                for value in schema.values():
                    visit(value)
            elif isinstance(schema, list):
                for value in schema:
                    visit(value)

        visit(AGENT_DECISION_SCHEMA)

    def test_request_is_a_copy_of_episode_state(self):
        request = self.seed_request()
        request["state"]["study"]["lux"] = 999
        episode = load_json(BENCH_ROOT / "data" / "seeds" / "HC-SEED-001.json")
        self.assertEqual(80, episode["initial_state"]["values"]["study"]["lux"])

    def test_specialist_request_only_contains_observable_or_writable_state(self):
        request = self.seed_request()
        self.assertEqual({"study": {"lux": 80}, "devices": {"study_light": "off"}}, request["state"])
        self.assertNotIn("bedroom", request["state"])

    def test_responses_adapter_parses_and_logs_structured_decision(self):
        captured = {}

        def transport(payload, headers, timeout):
            captured.update({"payload": payload, "headers": headers, "timeout": timeout})
            return {
                "id": "resp_test",
                "model": "gpt-5.6-luna",
                "service_tier": "default",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(valid_decision())}]}],
                "usage": {"input_tokens": 100, "output_tokens": 50, "output_tokens_details": {"reasoning_tokens": 10}},
            }

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            client = OpenAIResponsesClient(
                api_key="test-secret",
                logger=EventLogger(log_path, "test-run"),
                transport=transport,
            )
            decision = client.decide(self.seed_request(), "Return a valid decision.")
            events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual("action_proposal", decision["response_type"])
        self.assertFalse(captured["payload"]["store"])
        self.assertTrue(captured["payload"]["text"]["format"]["strict"])
        self.assertEqual("Bearer test-secret", captured["headers"]["Authorization"])
        self.assertEqual(["model_call_started", "model_call_completed"], [event["event_type"] for event in events])
        self.assertNotIn("test-secret", json.dumps(events))
        self.assertEqual(10, events[-1]["reasoning_tokens"])

    def test_missing_key_fails_before_network(self):
        previous = os.environ.pop("OPENAI_API_KEY", None)
        try:
            client = OpenAIResponsesClient(api_key=None, transport=lambda *_: self.fail("network called"))
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                client.decide(self.seed_request(), "test")
        finally:
            if previous is not None:
                os.environ["OPENAI_API_KEY"] = previous

    def test_protocol_dry_run_covers_all_seed_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot.jsonl"
            decisions = run(provider="dry-run", output_path=output)
            events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(8, len(decisions))
        self.assertEqual(8, sum(event["event_type"] == "agent_decision_validated" for event in events))
        self.assertEqual("run_completed", events[-1]["event_type"])

    def test_deepseek_adapter_uses_its_own_key_and_current_endpoint(self):
        previous_deepseek = os.environ.pop("DEEPSEEK_API_KEY", None)
        previous_openai = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "must-not-be-used"
        try:
            client = DeepSeekResponsesClient()
            self.assertIsNone(client.api_key)
            self.assertEqual("DEEPSEEK_API_KEY", client.api_key_env)
            self.assertEqual("https://api.deepseek.com", client.base_url)
            self.assertEqual("deepseek-flash", client.model)
            self.assertEqual("none", client.reasoning_effort)
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                client.decide(self.seed_request(), "test")
        finally:
            if previous_deepseek is not None:
                os.environ["DEEPSEEK_API_KEY"] = previous_deepseek
            if previous_openai is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous_openai

    def test_deepseek_payload_uses_non_thinking_mode(self):
        client = DeepSeekResponsesClient(api_key="test-secret", transport=lambda *_: {})
        payload = client.build_payload(self.seed_request(), "test")
        self.assertEqual("deepseek-flash", payload["model"])
        self.assertEqual({"effort": "none"}, payload["reasoning"])

    def test_nested_schema_violation_is_rejected(self):
        decision = valid_decision()
        requirement = {
            "path": "living_room.occupied",
            "op": "eq",
            "value_json": "false",
            "range_min": None,
            "range_max": None,
        }
        decision["actions"][0]["requires"] = [requirement]
        errors = validate_agent_decision(decision)
        self.assertTrue(any("missing value" in error for error in errors))
        self.assertTrue(any("unexpected value_json" in error for error in errors))

    def test_native_json_values_are_accepted(self):
        decision = valid_decision()
        decision["actions"][0]["parameters"] = [{
            "name": "temperature_c",
            "value": 24,
        }]
        decision["actions"][0]["requires"] = [{
            "path": "living_room.occupied",
            "op": "between",
            "value": None,
            "range_min": 0,
            "range_max": 1,
        }]
        self.assertEqual([], validate_agent_decision(decision))

    def test_more_than_one_action_is_rejected(self):
        decision = valid_decision()
        decision["actions"].append(dict(decision["actions"][0], proposal_id="p2"))
        errors = validate_agent_decision(decision)
        self.assertTrue(any("at most one action" in error for error in errors))

    def test_deepseek_retries_one_invalid_structured_output(self):
        calls = []

        def transport(payload, headers, timeout):
            calls.append(payload)
            body = {"type": "noop"} if len(calls) == 1 else valid_decision()
            return {
                "id": f"resp_{len(calls)}",
                "model": "deepseek-flash",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(body)}]}],
                "usage": {"input_tokens": 10, "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 0}},
            }

        client = DeepSeekResponsesClient(api_key="test-secret", transport=transport)
        decision = client.decide(self.seed_request(), "Return a valid decision.")
        self.assertEqual("action_proposal", decision["response_type"])
        self.assertEqual(2, len(calls))
        self.assertIn("failed protocol validation", calls[1]["instructions"])


if __name__ == "__main__":
    unittest.main()
