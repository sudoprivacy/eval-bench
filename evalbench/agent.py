"""Thin async wrapper around `claude_agent_sdk.ClaudeSDKClient`.

Drives a single prompt through the Claude Agent SDK with proper
subprocess lifecycle (via `async with`, so cancellation disconnects
the underlying `claude` CLI cleanly) and collects:

  - final text, turns, tool-call count, token usage, cost
  - termination reason
  - a full transcript of assistant/tool-result/rate-limit events
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .metrics import Termination, TokenUsage


@dataclass
class AgentRunResult:
    final_text: str = ""
    turns: int = 0
    tool_calls: int = 0
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float | None = None
    termination: str = Termination.completed.value
    error: str | None = None
    wall_ms: int = 0
    rate_limited: bool = False
    transcript: list[dict[str, Any]] = field(default_factory=list)


def _extract_usage(usage: dict | None) -> TokenUsage:
    if not usage:
        return TokenUsage()
    return TokenUsage(
        input=int(usage.get("input_tokens", 0) or 0),
        output=int(usage.get("output_tokens", 0) or 0),
        cache_read=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_create=int(usage.get("cache_creation_input_tokens", 0) or 0),
    )


def _tool_result_text(content: Any) -> str:
    """Flatten a ToolResultBlock.content (str | list | None) to a string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", "") or str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


async def _drive(prompt: str, options: ClaudeAgentOptions) -> AgentRunResult:
    result = AgentRunResult(termination=Termination.error.value,
                            error="no ResultMessage received")
    got_result = False

    # `async with` guarantees disconnect() — and therefore the `claude`
    # subprocess termination — even if the caller cancels us on timeout.
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        try:
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    entry: dict[str, Any] = {
                        "kind": "assistant",
                        "text": [],
                        "tool_uses": [],
                        "thinking": [],
                    }
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            entry["text"].append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            result.tool_calls += 1
                            entry["tool_uses"].append({
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            })
                        elif isinstance(block, ThinkingBlock):
                            entry["thinking"].append(block.thinking)
                    # Drop empty assistant messages (pure control-plane noise).
                    if entry["text"] or entry["tool_uses"] or entry["thinking"]:
                        result.transcript.append(entry)

                elif isinstance(msg, UserMessage):
                    if isinstance(msg.content, list):
                        for block in msg.content:
                            if isinstance(block, ToolResultBlock):
                                result.transcript.append({
                                    "kind": "tool_result",
                                    "tool_use_id": block.tool_use_id,
                                    "is_error": bool(block.is_error),
                                    "content": _tool_result_text(block.content),
                                })

                elif isinstance(msg, RateLimitEvent):
                    info = msg.rate_limit_info
                    status = info.status
                    result.transcript.append({
                        "kind": "rate_limit",
                        "status": status,
                        "type": info.rate_limit_type,
                        "resets_at": info.resets_at,
                        "utilization": info.utilization,
                    })
                    if status == "rejected":
                        result.rate_limited = True
                        # Abandon this attempt; the wrapping retry logic
                        # decides whether to try again.
                        result.termination = Termination.error.value
                        result.error = "rate limit rejected"
                        break

                elif isinstance(msg, ResultMessage):
                    got_result = True
                    result.turns = msg.num_turns
                    result.tokens = _extract_usage(msg.usage)
                    result.cost_usd = msg.total_cost_usd
                    result.final_text = msg.result or ""
                    subtype = msg.subtype or ""
                    if subtype == "success":
                        result.termination = Termination.completed.value
                        result.error = None
                    elif "max_turns" in subtype or msg.stop_reason in {
                        "max_turns", "turn_limit",
                    }:
                        result.termination = Termination.max_turns.value
                        result.error = None
                    elif msg.is_error:
                        result.termination = Termination.error.value
                        result.error = (
                            (msg.errors[0] if msg.errors else None)
                            or msg.result
                            or subtype
                            or "unknown error"
                        )
                    else:
                        result.termination = Termination.completed.value
                        result.error = None
        except Exception as exc:  # pragma: no cover — SDK error paths
            # Only surface stream-level exceptions if we never got a
            # ResultMessage. Some SDK versions emit a subprocess teardown
            # error *after* a valid ResultMessage, which would otherwise
            # clobber a good run.
            if not got_result:
                result.termination = Termination.error.value
                result.error = f"{type(exc).__name__}: {exc}"

    return result


_RATE_LIMIT_BACKOFF_BASE_S = 4.0
_RATE_LIMIT_BACKOFF_CAP_S = 60.0


async def _rate_limit_sleep(attempt: int) -> None:
    """Exponential backoff with mild jitter; attempt is 1-based."""
    import random
    delay = min(
        _RATE_LIMIT_BACKOFF_BASE_S * (2 ** (attempt - 1)),
        _RATE_LIMIT_BACKOFF_CAP_S,
    )
    delay += random.uniform(0, delay * 0.25)
    await asyncio.sleep(delay)


async def run_agent(
    prompt: str,
    options: ClaudeAgentOptions,
    *,
    timeout_s: int,
    max_rate_limit_retries: int = 2,
    _drive_fn=None,       # test hook
    _sleep_fn=None,       # test hook
) -> AgentRunResult:
    """Run `prompt` through the SDK with a wall-clock timeout and
    bounded retries on rate-limit rejections.

    On timeout the `ClaudeSDKClient` async-context-manager exits,
    which disconnects the underlying subprocess — no orphan process.
    """
    drive = _drive_fn or _drive
    sleep = _sleep_fn or _rate_limit_sleep

    t0 = time.perf_counter()
    attempts = 0
    prior_transcript: list[dict] = []

    while True:
        attempts += 1
        try:
            result = await asyncio.wait_for(
                drive(prompt, options), timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            result = AgentRunResult(
                termination=Termination.timeout.value,
                error=f"timeout after {timeout_s}s",
                transcript=prior_transcript,
            )
            result.wall_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # Prepend prior attempts' transcripts with a retry marker.
        if prior_transcript:
            result.transcript = prior_transcript + [
                {"kind": "retry_marker", "attempt": attempts - 1},
            ] + result.transcript

        if result.rate_limited and attempts <= max_rate_limit_retries:
            prior_transcript = list(result.transcript)
            await sleep(attempts)
            continue

        result.wall_ms = int((time.perf_counter() - t0) * 1000)
        return result
