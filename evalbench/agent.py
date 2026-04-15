"""Thin async wrapper around `claude_agent_sdk.query`.

Drives a single prompt through the Claude Agent SDK and collects the
metrics we care about for the eval bench: final text, turns, tool-call
count, token usage, cost, termination reason.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
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


def _extract_usage(usage: dict | None) -> TokenUsage:
    if not usage:
        return TokenUsage()
    return TokenUsage(
        input=int(usage.get("input_tokens", 0) or 0),
        output=int(usage.get("output_tokens", 0) or 0),
        cache_read=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_create=int(usage.get("cache_creation_input_tokens", 0) or 0),
    )


async def _drive(prompt: str, options: ClaudeAgentOptions) -> AgentRunResult:
    result = AgentRunResult(termination=Termination.error.value,
                            error="no ResultMessage received")
    got_result = False
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        result.tool_calls += 1
                    elif isinstance(block, TextBlock):
                        pass
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
                elif "max_turns" in subtype or msg.stop_reason in {"max_turns", "turn_limit"}:
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
        # Only surface stream-level exceptions if we never got a ResultMessage.
        # Some SDK versions emit a subprocess teardown error *after* a valid
        # ResultMessage, which would otherwise clobber a good run.
        if not got_result:
            result.termination = Termination.error.value
            result.error = f"{type(exc).__name__}: {exc}"
    return result


async def run_agent(
    prompt: str,
    options: ClaudeAgentOptions,
    *,
    timeout_s: int,
) -> AgentRunResult:
    """Run `prompt` through the SDK with a wall-clock timeout."""
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(_drive(prompt, options), timeout=timeout_s)
    except asyncio.TimeoutError:
        return AgentRunResult(
            termination=Termination.timeout.value,
            error=f"timeout after {timeout_s}s",
            wall_ms=int((time.perf_counter() - t0) * 1000),
        )
    result.wall_ms = int((time.perf_counter() - t0) * 1000)
    return result
