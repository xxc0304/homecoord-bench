"""Replay recorded model decisions without issuing new API requests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReplayClient:
    def __init__(self, event_log: Path):
        events = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.records = [event for event in events if event.get("event_type") == "model_call_completed"]
        self.index = 0
        self.last_latency_ms = 0

    def decide(self, agent_request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        if self.index >= len(self.records):
            raise RuntimeError("replay log has no remaining completed model call")
        record = self.records[self.index]
        self.index += 1
        self.last_latency_ms = max(1, round(record["latency_ms"]))
        return record["decision"]

    def assert_consumed(self) -> None:
        if self.index != len(self.records):
            raise RuntimeError(f"replay left {len(self.records) - self.index} unused model decisions")


class MemoryReplayClient:
    """Replay decisions with logical call latencies already aggregated."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records
        self.index = 0
        self.last_latency_ms = 0

    def decide(self, agent_request: dict[str, Any], instructions: str = "") -> dict[str, Any]:
        if self.index >= len(self.records):
            raise RuntimeError("memory replay has no remaining decision")
        record = self.records[self.index]
        self.index += 1
        self.last_latency_ms = max(1, round(record["logical_latency_ms"]))
        return record["decision"]

    def assert_consumed(self) -> None:
        if self.index != len(self.records):
            raise RuntimeError(f"memory replay left {len(self.records) - self.index} decisions")
