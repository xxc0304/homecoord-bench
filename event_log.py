"""Append-only JSONL event logger for latency and cost measurements."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any


class EventLogger:
    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.started_ns = perf_counter_ns()
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        now_ns = perf_counter_ns()
        event = {
            "run_id": self.run_id,
            "event_type": event_type,
            "wall_time_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((now_ns - self.started_ns) / 1_000_000, 3),
            **fields,
        }
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        return event
