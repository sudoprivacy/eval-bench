"""Tests for parallel suite execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evalbench.agent import AgentRunResult
from evalbench.config import load_suite
from evalbench.metrics import Termination, TokenUsage
from evalbench.runner import run_suite


def _make_suite(tmp_path: Path, n_cases: int = 4,
                concurrency: int = 2, trials: int = 1) -> Path:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text(
        "target:\n  type: prompt\n  system_prompt: hi\n"
        f"run:\n  concurrency: {concurrency}\n  trials: {trials}\n"
    )
    for i in range(n_cases):
        (suite_dir / f"case_{i}.yaml").write_text(
            f"id: c{i}\nprompt: p{i}\n"
        )
    return suite_dir


@pytest.mark.asyncio
async def test_run_suite_writes_all_results(tmp_path: Path) -> None:
    suite = load_suite(_make_suite(tmp_path, n_cases=5, concurrency=3, trials=2))
    results_path = tmp_path / "out" / "results.jsonl"

    async def fake(prompt, options):
        return AgentRunResult(
            termination=Termination.completed.value, turns=1,
            tokens=TokenUsage(input=10, output=5),
        )

    results = await run_suite(suite, results_path, agent_fn=fake)
    assert len(results) == 5 * 2

    lines = results_path.read_text().strip().splitlines()
    assert len(lines) == 5 * 2
    # All lines are valid JSON and contain case_id.
    for line in lines:
        obj = json.loads(line)
        assert "case_id" in obj and "trial" in obj


@pytest.mark.asyncio
async def test_run_suite_respects_concurrency(tmp_path: Path) -> None:
    """At most `concurrency` agent calls should run simultaneously."""
    suite = load_suite(_make_suite(tmp_path, n_cases=6, concurrency=2, trials=1))
    results_path = tmp_path / "out" / "r.jsonl"

    in_flight = {"n": 0, "peak": 0}

    async def fake(prompt, options):
        in_flight["n"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["n"])
        await asyncio.sleep(0.02)
        in_flight["n"] -= 1
        return AgentRunResult(termination=Termination.completed.value)

    await run_suite(suite, results_path, agent_fn=fake)
    assert in_flight["peak"] <= 2
    assert in_flight["peak"] >= 2  # we expect some parallelism


@pytest.mark.asyncio
async def test_run_suite_filter_glob(tmp_path: Path) -> None:
    suite = load_suite(_make_suite(tmp_path, n_cases=4))
    results_path = tmp_path / "out" / "r.jsonl"

    async def fake(prompt, options):
        return AgentRunResult(termination=Termination.completed.value)

    results = await run_suite(
        suite, results_path, filter_glob="c[01]", agent_fn=fake,
    )
    ids = sorted(r.case_id for r in results)
    assert ids == ["c0", "c1"]


@pytest.mark.asyncio
async def test_run_suite_on_result_fires_per_case(tmp_path: Path) -> None:
    suite = load_suite(_make_suite(tmp_path, n_cases=3))
    results_path = tmp_path / "out" / "r.jsonl"

    async def fake(prompt, options):
        return AgentRunResult(termination=Termination.completed.value)

    seen = []
    def hook(result):
        seen.append(result.case_id)

    await run_suite(suite, results_path, agent_fn=fake, on_result=hook)
    assert sorted(seen) == ["c0", "c1", "c2"]
