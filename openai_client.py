"""Minimal Responses API adapter using only the Python standard library."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from time import perf_counter_ns
from typing import Any, Callable

from .event_log import EventLogger
from .protocol import AGENT_DECISION_SCHEMA, assert_agent_decision

Transport = Callable[[dict[str, Any], dict[str, str], float], dict[str, Any]]


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        model: str = "gpt-5.6-luna",
        reasoning_effort: str = "low",
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        provider: str = "openai",
        timeout_seconds: float = 60.0,
        max_attempts: int = 1,
        base_url: str = "https://api.openai.com/v1",
        logger: EventLogger | None = None,
        transport: Transport | None = None,
    ):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.api_key_env = api_key_env
        self.provider = provider
        self.api_key = api_key or os.environ.get(api_key_env)
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.transport = transport or self._http_transport

    def _http_transport(self, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.provider} API HTTP {exc.code}: {body[:1000]}") from exc

    def build_payload(self, agent_request: dict[str, Any], instructions: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps(agent_request, ensure_ascii=False, separators=(",", ":")),
            "reasoning": {"effort": self.reasoning_effort},
            "max_output_tokens": 1200,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "homecoord_agent_decision",
                    "strict": True,
                    "schema": AGENT_DECISION_SCHEMA,
                }
            },
        }

    @staticmethod
    def _extract_output_text(response: dict[str, Any]) -> str:
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise RuntimeError(f"model refusal: {content.get('refusal', '')}")
                if content.get("type") == "output_text":
                    return content["text"]
        raise RuntimeError("response did not contain output_text")

    def decide(self, agent_request: dict[str, Any], instructions: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(f"{self.api_key_env} is not configured")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        current_instructions = instructions
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            payload = self.build_payload(agent_request, current_instructions)
            started = perf_counter_ns()
            response: dict[str, Any] | None = None
            raw_output: str | None = None
            if self.logger:
                self.logger.emit(
                    "model_call_started",
                    request_id=agent_request["request_id"],
                    episode_id=agent_request["episode_id"],
                    architecture=agent_request.get("architecture"),
                    agent_id=agent_request.get("agent", {}).get("agent_id"),
                    task_id=agent_request.get("task", {}).get("task_id"),
                    provider=self.provider,
                    model=self.model,
                    reasoning_effort=self.reasoning_effort,
                    attempt=attempt,
                )
            try:
                response = self.transport(payload, headers, self.timeout_seconds)
                raw_output = self._extract_output_text(response)
                decision = json.loads(raw_output)
                assert_agent_decision(decision)
            except Exception as exc:
                last_error = exc
                usage = response.get("usage", {}) if response else {}
                if self.logger:
                    self.logger.emit(
                        "model_call_failed",
                        request_id=agent_request["request_id"],
                        provider=self.provider,
                        model=self.model,
                        attempt=attempt,
                        latency_ms=round((perf_counter_ns() - started) / 1_000_000, 3),
                        error_type=type(exc).__name__,
                        error=str(exc)[:1000],
                        raw_output=raw_output[:4000] if raw_output else None,
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        reasoning_tokens=usage.get("output_tokens_details", {}).get("reasoning_tokens"),
                    )
                if attempt < self.max_attempts:
                    current_instructions = (
                        instructions
                        + "\nYour previous response failed protocol validation: "
                        + str(exc)[:500]
                        + "\nReturn a corrected object. Use response_type, not type. "
                        + "The actions array may contain at most one action. Use native JSON scalar values in value, never value_json; every requirement must include range_min and range_max, using null except for between."
                    )
                    continue
                raise
            usage = response.get("usage", {})
            if self.logger:
                self.logger.emit(
                    "model_call_completed",
                    request_id=agent_request["request_id"],
                    response_id=response.get("id"),
                    provider=self.provider,
                    attempt=attempt,
                    latency_ms=round((perf_counter_ns() - started) / 1_000_000, 3),
                    model=response.get("model", self.model),
                    service_tier=response.get("service_tier"),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    reasoning_tokens=usage.get("output_tokens_details", {}).get("reasoning_tokens"),
                    decision=decision,
                )
            return decision
        raise last_error or RuntimeError("model call failed")
