"""Smoke tests for the runner using an injected fake agent_fn.

These exercise the full case-execution path — fixtures, setup commands,
grading, JSONL output — without invoking the real Claude Agent SDK.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalbench.agent import AgentRunResult
from evalbench.config import load_suite
from evalbench.metrics import Termination, TokenUsage
from evalbench.runner import append_jsonl, run_case_trial


def _make_suite(tmp_path: Path, *, grade_yaml: str = "", setup_yaml: str = "",
                fixtures_yaml: str = "", extra: str = "") -> Path:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text(
        "target:\n  type: prompt\n  system_prompt: hi\n"
    )
    (suite_dir / "case_a.yaml").write_text(
        "id: a\n"
        "prompt: do it\n"
        f"{setup_yaml}"
        f"{fixtures_yaml}"
        f"{grade_yaml}"
        f"{extra}"
    )
    return suite_dir


def _ok_agent_factory(write_file: Path | None = None,
                      content: str = "hello world"):
    async def fake(prompt, options):  # type: ignore[no-untyped-def]
        if write_file is not None:
            (Path(options.cwd) / write_file).write_text(content)
        return AgentRunResult(
            final_text="done", turns=3, tool_calls=1,
            tokens=TokenUsage(input=100, output=50),
            cost_usd=0.01, termination=Termination.completed.value,
        )
    return fake


@pytest.mark.asyncio
async def test_case_passes_with_file_grader(tmp_path: Path) -> None:
    suite_dir = _make_suite(tmp_path, grade_yaml=(
        "grade:\n"
        "  - type: file_exists\n"
        "    path: out.txt\n"
        "  - type: file_contains\n"
        "    path: out.txt\n"
        "    needle: world\n"
    ))
    suite = load_suite(suite_dir)
    result = await run_case_trial(
        suite.cases[0], suite, trial=1,
        agent_fn=_ok_agent_factory(write_file=Path("out.txt")),
    )
    assert result.passed is True
    assert result.turns == 3
    assert result.tool_calls == 1
    assert result.tokens.input == 100
    assert [g.passed for g in result.grades] == [True, True]


@pytest.mark.asyncio
async def test_case_fails_when_grader_fails(tmp_path: Path) -> None:
    suite_dir = _make_suite(tmp_path, grade_yaml=(
        "grade:\n"
        "  - type: file_exists\n"
        "    path: never.txt\n"
    ))
    suite = load_suite(suite_dir)
    result = await run_case_trial(
        suite.cases[0], suite, trial=1,
        agent_fn=_ok_agent_factory(write_file=None),
    )
    assert result.passed is False
    assert result.grades[0].passed is False


@pytest.mark.asyncio
async def test_case_fails_on_non_completed_termination(tmp_path: Path) -> None:
    suite_dir = _make_suite(tmp_path)
    suite = load_suite(suite_dir)

    async def timed_out(prompt, options):
        return AgentRunResult(
            termination=Termination.timeout.value, error="timeout after 5s",
        )

    result = await run_case_trial(suite.cases[0], suite, 1, agent_fn=timed_out)
    assert result.passed is False
    assert result.termination == "timeout"
    assert "timeout" in (result.error or "")


@pytest.mark.asyncio
async def test_setup_command_runs_and_fixtures_copy(tmp_path: Path) -> None:
    suite_dir = _make_suite(tmp_path, setup_yaml=(
        "setup:\n"
        "  - \"echo hi > prepared.txt\"\n"
    ), fixtures_yaml=(
        "fixtures:\n"
        "  - fixture.txt\n"
    ), grade_yaml=(
        "grade:\n"
        "  - type: file_exists\n"
        "    path: prepared.txt\n"
        "  - type: file_exists\n"
        "    path: fixture.txt\n"
    ))
    (suite_dir / "fixture.txt").write_text("fixture content")
    suite = load_suite(suite_dir)
    result = await run_case_trial(
        suite.cases[0], suite, 1,
        agent_fn=_ok_agent_factory(),
    )
    assert result.passed is True


@pytest.mark.asyncio
async def test_llm_judge_is_skipped_and_fails_until_implemented(tmp_path: Path) -> None:
    suite_dir = _make_suite(tmp_path, grade_yaml=(
        "grade:\n"
        "  - type: llm_judge\n"
        "    rubric: \"judge me\"\n"
    ))
    suite = load_suite(suite_dir)
    result = await run_case_trial(
        suite.cases[0], suite, 1, agent_fn=_ok_agent_factory(),
    )
    assert result.passed is False
    assert result.grades[0].type == "llm_judge"
    assert result.grades[0].passed is False


def test_append_jsonl_roundtrip(tmp_path: Path) -> None:
    from evalbench.metrics import CaseResult, GradeRecord
    out = tmp_path / "r" / "results.jsonl"
    r1 = CaseResult(case_id="a", trial=1, passed=True,
                    grades=[GradeRecord("file_exists", True, "ok")],
                    tokens=TokenUsage(input=1, output=2), turns=1)
    r2 = CaseResult(case_id="b", trial=1, passed=False)
    append_jsonl(out, r1)
    append_jsonl(out, r2)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    d1 = json.loads(lines[0])
    assert d1["case_id"] == "a" and d1["passed"] is True
    assert d1["tokens"] == {"input": 1, "output": 2, "cache_read": 0, "cache_create": 0}
    assert d1["grades"][0]["type"] == "file_exists"
