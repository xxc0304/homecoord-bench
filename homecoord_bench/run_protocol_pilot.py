"""Build requests and validate structured decisions for every seed task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from evaluate import ROOT, load_json
from runtime.dry_run import DryRunClient
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.openai_client import OpenAIResponsesClient
from runtime.protocol import build_agent_request

INSTRUCTIONS = """You are a smart-home specialist agent. Return exactly one decision matching the supplied schema. Propose only actions allowed by your tools. Base actions on the supplied state_version. Do not claim an action has executed; you are only proposing or coordinating it. Parameter and requirement values must be native JSON scalar values in the `value` field; never encode JSON inside a string and never use `value_json`. Every requirement must also include range_min and range_max: use null for both except for between, where value is null and the two bounds are numbers."""


def run(
    *,
    provider: str = "dry-run",
    output_path: Path | None = None,
    model: str | None = None,
) -> list[dict]:
    run_id = f"protocol-{uuid4()}"
    output_path = output_path or ROOT / "runs" / f"{run_id}.jsonl"
    logger = EventLogger(output_path, run_id)
    if provider == "deepseek":
        model = model or "deepseek-flash"
        client = DeepSeekResponsesClient(logger=logger, model=model)
    elif provider == "openai":
        model = model or "gpt-5.6-luna"
        client = OpenAIResponsesClient(logger=logger, model=model)
    elif provider == "dry-run":
        client = DryRunClient()
        model = "deterministic"
    else:
        raise ValueError(f"unsupported provider: {provider}")
    decisions = []
    logger.emit("run_started", provider=provider, mode="dry_run" if provider == "dry-run" else "live", model=model)
    for episode_path in sorted((ROOT / "data" / "seeds").glob("*.json")):
        episode = load_json(episode_path)
        agent_by_id = {agent["agent_id"]: agent for agent in episode["agents"]}
        for task in episode["task_stream"]:
            agent = agent_by_id[task["agent_id"]]
            request = build_agent_request(
                episode,
                agent,
                task,
                architecture="IndependentMultiAgent",
                current_time_ms=task["release_at_ms"],
            )
            logger.emit(
                "agent_request_created",
                request_id=request["request_id"],
                episode_id=episode["episode_id"],
                agent_id=agent["agent_id"],
                state_version=request["state_version"],
                request=request,
            )
            try:
                decision = client.decide(request, INSTRUCTIONS)
            except Exception as exc:
                logger.emit(
                    "agent_decision_rejected",
                    request_id=request["request_id"],
                    episode_id=episode["episode_id"],
                    agent_id=agent["agent_id"],
                    error_type=type(exc).__name__,
                    error=str(exc)[:1000],
                )
                decisions.append({"request": request, "error": f"{type(exc).__name__}: {exc}"})
                continue
            logger.emit(
                "agent_decision_validated",
                request_id=request["request_id"],
                episode_id=episode["episode_id"],
                agent_id=agent["agent_id"],
                response_type=decision["response_type"],
                action_count=len(decision["actions"]),
                decision=decision,
            )
            decisions.append({"request": request, "decision": decision})
    failures = sum("error" in row for row in decisions)
    logger.emit("run_completed", decisions=len(decisions) - failures, failures=failures)
    return decisions


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["dry-run", "deepseek", "openai"], default="dry-run")
    parser.add_argument("--model", help="override the live provider model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = run(provider=args.provider, output_path=args.output, model=args.model)
    failures = sum("error" in row for row in rows)
    print(json.dumps({"provider": args.provider, "decisions": len(rows) - failures, "failures": failures}, ensure_ascii=False))
