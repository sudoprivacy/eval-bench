"""Tests for `run_agent`'s timeout + rate-limit retry logic.

Uses `_drive_fn` injection so the real Claude SDK is never called.
"""

from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from evalbench.agent import AgentRunResult, run_agent
from evalbench.metrics import Termination


def _opts() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(system_prompt="test", allowed_tools=[])


@pytest.mark.asyncio
async def test_retries_on_rate_limit_and_merges_transcripts() -> None:
    calls = {"n": 0}

    async def fake_drive(prompt, options):
        calls["n"] += 1
        if calls["n"] < 3:
            return AgentRunResult(
                termination=Termination.error.value,
                error="rate limit rejected",
                rate_limited=True,
                transcript=[
                    {"kind": "rate_limit", "status": "rejected",
                     "attempt": calls["n"]},
                ],
            )
        return AgentRunResult(
            termination=Termination.completed.value,
            final_text="ok",
            transcript=[{"kind": "assistant", "text": ["hi"],
                         "tool_uses": []}],
        )

    async def no_sleep(attempt):
        return None

    r = await run_agent(
        "p", _opts(), timeout_s=5, max_rate_limit_retries=3,
        _drive_fn=fake_drive, _sleep_fn=no_sleep,
    )
    assert r.termination == Termination.completed.value
    assert calls["n"] == 3
    # Transcript: 2 rate-limit entries + 2 retry markers + 1 assistant entry
    kinds = [e["kind"] for e in r.transcript]
    assert kinds.count("rate_limit") == 2
    assert kinds.count("retry_marker") == 2
    assert kinds.count("assistant") == 1


@pytest.mark.asyncio
async def test_gives_up_after_max_retries() -> None:
    async def always_rate_limited(prompt, options):
        return AgentRunResult(
            termination=Termination.error.value,
            error="rate limit rejected",
            rate_limited=True,
            transcript=[{"kind": "rate_limit", "status": "rejected"}],
        )

    async def no_sleep(attempt):
        return None

    r = await run_agent(
        "p", _opts(), timeout_s=5, max_rate_limit_retries=2,
        _drive_fn=always_rate_limited, _sleep_fn=no_sleep,
    )
    assert r.termination == Termination.error.value
    assert r.rate_limited is True
    # 3 attempts total (initial + 2 retries), so 2 retry markers
    kinds = [e["kind"] for e in r.transcript]
    assert kinds.count("retry_marker") == 2


@pytest.mark.asyncio
async def test_timeout_terminates_fast_and_records() -> None:
    async def slow(prompt, options):
        await asyncio.sleep(10)
        return AgentRunResult(termination=Termination.completed.value)

    r = await run_agent(
        "p", _opts(), timeout_s=0, _drive_fn=slow,
    )
    # timeout=0 fires immediately.
    assert r.termination == Termination.timeout.value
    assert "timeout" in (r.error or "")


@pytest.mark.asyncio
async def test_no_retry_on_terminal_success() -> None:
    calls = {"n": 0}

    async def fake(prompt, options):
        calls["n"] += 1
        return AgentRunResult(
            termination=Termination.completed.value, final_text="ok",
        )

    async def no_sleep(attempt):
        return None

    r = await run_agent(
        "p", _opts(), timeout_s=5, _drive_fn=fake, _sleep_fn=no_sleep,
    )
    assert r.termination == Termination.completed.value
    assert calls["n"] == 1
