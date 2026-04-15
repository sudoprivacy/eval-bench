"""Tests for evalbench.grade (sync evaluator + judge parsing + routing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalbench.grade import (
    FileContainsGrader,
    FileExistsGrader,
    GradeResult,
    JudgeContext,
    LlmJudgeGrader,
    ShellGrader,
    _parse_judge_output,
    evaluate,
    evaluate_sync,
)


def test_file_exists_grader(tmp_path: Path) -> None:
    (tmp_path / "hi.txt").write_text("x")
    r = evaluate_sync(FileExistsGrader(path="hi.txt"), tmp_path)
    assert r.passed is True
    r2 = evaluate_sync(FileExistsGrader(path="missing"), tmp_path)
    assert r2.passed is False


def test_file_contains_literal_and_regex(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world")
    assert evaluate_sync(FileContainsGrader(path="a.txt", needle="world"), tmp_path).passed
    assert not evaluate_sync(FileContainsGrader(path="a.txt", needle="zzz"), tmp_path).passed
    assert evaluate_sync(
        FileContainsGrader(path="a.txt", needle=r"w\w+d", regex=True), tmp_path,
    ).passed


def test_shell_grader_exit_code(tmp_path: Path) -> None:
    assert evaluate_sync(ShellGrader(command="true"), tmp_path).passed
    assert not evaluate_sync(ShellGrader(command="false"), tmp_path).passed


@pytest.mark.parametrize("text, expected", [
    ('{"passed": true, "reason": "ok"}', (True, "ok")),
    ('prose before {"passed": false, "reason": "nope"} and after', (False, "nope")),
    ('{"passed": 1, "reason": "truthy"}', (True, "truthy")),
    ("no json here", None),
    ('{"reason": "no passed key"}', None),
    ("{not valid json}", None),
])
def test_parse_judge_output(text, expected) -> None:
    assert _parse_judge_output(text) == expected


@pytest.mark.asyncio
async def test_evaluate_routes_sync_graders(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    r = await evaluate(FileExistsGrader(path="a.txt"), tmp_path)
    assert r.passed is True


@pytest.mark.asyncio
async def test_evaluate_llm_judge_uses_injected_fn(tmp_path: Path) -> None:
    captured = {}

    async def fake_judge(grader, cwd, ctx):
        captured["rubric"] = grader.rubric
        captured["prompt"] = ctx.case_prompt
        return GradeResult("llm_judge", True, "yes")

    ctx = JudgeContext(case_prompt="do X", agent_final_text="did X")
    r = await evaluate(
        LlmJudgeGrader(rubric="did it do X?"), tmp_path,
        context=ctx, judge_fn=fake_judge,
    )
    assert r.passed is True
    assert captured["rubric"] == "did it do X?"
    assert captured["prompt"] == "do X"


@pytest.mark.asyncio
async def test_evaluate_llm_judge_without_context_fails(tmp_path: Path) -> None:
    r = await evaluate(LlmJudgeGrader(rubric="?"), tmp_path)
    assert r.passed is False
    assert "no JudgeContext" in r.detail


@pytest.mark.asyncio
async def test_default_judge_model_is_not_target_model(
    tmp_path: Path, monkeypatch,
) -> None:
    """The default judge uses its own model, never falls back to the target's."""
    from evalbench import grade as grade_module
    captured = {}

    async def fake_run_agent(prompt, options, *, timeout_s):
        captured["model"] = options.model
        return type("R", (), {
            "termination": "completed",
            "final_text": '{"passed": true, "reason": "ok"}',
            "error": None,
        })()

    monkeypatch.setattr(grade_module, "DEFAULT_JUDGE_MODEL", "some-judge-model")
    monkeypatch.setattr("evalbench.agent.run_agent", fake_run_agent)

    ctx = JudgeContext(
        case_prompt="p", agent_final_text="x", model="TARGET-MODEL",
    )
    r = await evaluate(LlmJudgeGrader(rubric="r"), tmp_path, context=ctx)
    assert r.passed is True
    assert captured["model"] == "some-judge-model"
    assert captured["model"] != "TARGET-MODEL"


@pytest.mark.asyncio
async def test_per_grader_model_overrides_default(
    tmp_path: Path, monkeypatch,
) -> None:
    from evalbench import grade as grade_module
    captured = {}

    async def fake_run_agent(prompt, options, *, timeout_s):
        captured["model"] = options.model
        return type("R", (), {
            "termination": "completed",
            "final_text": '{"passed": false, "reason": "no"}',
            "error": None,
        })()

    monkeypatch.setattr(grade_module, "DEFAULT_JUDGE_MODEL", "default-judge")
    monkeypatch.setattr("evalbench.agent.run_agent", fake_run_agent)

    ctx = JudgeContext(case_prompt="p", agent_final_text="x", model="target")
    r = await evaluate(
        LlmJudgeGrader(rubric="r", model="explicit-judge"),
        tmp_path, context=ctx,
    )
    assert r.passed is False
    assert captured["model"] == "explicit-judge"


@pytest.mark.asyncio
async def test_judge_prompt_includes_evidence_files(
    tmp_path: Path, monkeypatch,
) -> None:
    """Evidence files must be embedded verbatim in the judge prompt."""
    captured = {}

    async def fake_run_agent(prompt, options, *, timeout_s):
        captured["prompt"] = prompt
        return type("R", (), {
            "termination": "completed",
            "final_text": '{"passed": true, "reason": "ok"}',
            "error": None,
        })()

    monkeypatch.setattr("evalbench.agent.run_agent", fake_run_agent)

    ctx = JudgeContext(
        case_prompt="greet Carol",
        agent_final_text="Done!",
        evidence_files={"greeting.txt": "Welcome, Carol!"},
    )
    r = await evaluate(LlmJudgeGrader(rubric="is it warm?"),
                       tmp_path, context=ctx)
    assert r.passed is True
    assert "Welcome, Carol!" in captured["prompt"]
    assert "greeting.txt" in captured["prompt"]


@pytest.mark.asyncio
async def test_judge_prompt_omits_evidence_section_when_empty(
    tmp_path: Path, monkeypatch,
) -> None:
    captured = {}

    async def fake_run_agent(prompt, options, *, timeout_s):
        captured["prompt"] = prompt
        return type("R", (), {
            "termination": "completed",
            "final_text": '{"passed": true}',
            "error": None,
        })()

    monkeypatch.setattr("evalbench.agent.run_agent", fake_run_agent)

    ctx = JudgeContext(case_prompt="p", agent_final_text="Done!",
                       evidence_files={})
    await evaluate(LlmJudgeGrader(rubric="r"), tmp_path, context=ctx)
    assert "Files in the working directory" not in captured["prompt"]
