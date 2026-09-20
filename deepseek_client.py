"""DeepSeek Responses API adapter for HomeCoord-Bench."""

from __future__ import annotations

from typing import Any

from .event_log import EventLogger
from .openai_client import OpenAIResponsesClient, Transport


class DeepSeekResponsesClient(OpenAIResponsesClient):
    def __init__(
        self,
        *,
        model: str = "deepseek-flash",
        reasoning_effort: str = "none",
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        max_attempts: int = 2,
        logger: EventLogger | None = None,
        transport: Transport | None = None,
    ):
        super().__init__(
            model=model,
            reasoning_effort=reasoning_effort,
            api_key=api_key,
            api_key_env="DEEPSEEK_API_KEY",
            provider="deepseek",
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            base_url="https://api.deepseek.com",
            logger=logger,
            transport=transport,
        )
