"""Grader data models and pass/fail evaluation.

In v1 each grader returns a boolean; a case passes iff *all* its graders
pass. Programmatic graders (file/shell) run synchronously; `llm_judge`
routes through the Claude Agent SDK via an injectable callable.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Awaitable, Callable, Literal, Union

from claude_agent_sdk import ClaudeAgentOptions
from pydantic import BaseModel, Field


class FileExistsGrader(BaseModel):
    type: Literal["file_exists"] = "file_exists"
    path: str


class FileContainsGrader(BaseModel):
    type: Literal["file_contains"] = "file_contains"
    path: str
    needle: str
    regex: bool = False


class ShellGrader(BaseModel):
    """Passes iff the given shell command exits 0 (run inside case cwd)."""

    type: Literal["shell"] = "shell"
    command: str


class LlmJudgeGrader(BaseModel):
    type: Literal["llm_judge"] = "llm_judge"
    rubric: str
    model: str | None = None


Grader = Annotated[
    Union[FileExistsGrader, FileContainsGrader, ShellGrader, LlmJudgeGrader],
    Field(discriminator="type"),
]


@dataclass(frozen=True)
class GradeResult:
    type: str
    passed: bool
    detail: str = ""


def evaluate_sync(grader: Grader, cwd: Path) -> GradeResult:
    """Evaluate graders that do not require an LLM call.

    `LlmJudgeGrader` is not handled here; callers route those to the
    async judge wired up in the runner step.
    """
    if isinstance(grader, FileExistsGrader):
        ok = (cwd / grader.path).exists()
        return GradeResult("file_exists", ok, f"path={grader.path}")

    if isinstance(grader, FileContainsGrader):
        target = cwd / grader.path
        if not target.exists():
            return GradeResult("file_contains", False, f"missing {grader.path}")
        text = target.read_text(errors="replace")
        ok = (re.search(grader.needle, text) is not None
              if grader.regex else grader.needle in text)
        return GradeResult("file_contains", ok, f"path={grader.path}")

    if isinstance(grader, ShellGrader):
        proc = subprocess.run(
            grader.command, shell=True, cwd=cwd, capture_output=True, text=True,
        )
        return GradeResult(
            "shell", proc.returncode == 0,
            f"exit={proc.returncode}",
        )

    raise TypeError(f"evaluate_sync cannot handle {type(grader).__name__}")


# -- LLM judge -----------------------------------------------------------

@dataclass(frozen=True)
class JudgeContext:
    """Evidence passed to an LLM judge."""

    case_prompt: str
    agent_final_text: str
    model: str | None = None


JudgeFn = Callable[["LlmJudgeGrader", Path, JudgeContext], Awaitable[GradeResult]]


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluation judge. You receive a rubric, the task "
    "that was given to an agent, and the agent's final output. Decide "
    "pass or fail. Reply with a single JSON object on one line — no "
    "prose, no code fences, no extra keys: "
    '{"passed": true|false, "reason": "short explanation"}'
)


def _parse_judge_output(text: str) -> tuple[bool, str] | None:
    """Pick the first JSON object out of `text` and extract passed/reason."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "passed" not in data:
        return None
    return bool(data["passed"]), str(data.get("reason", ""))


async def _default_judge(
    grader: "LlmJudgeGrader", cwd: Path, ctx: JudgeContext,
) -> GradeResult:
    # Imported here to avoid a circular import at module load.
    from .agent import run_agent
    from .metrics import Termination

    user_msg = (
        f"Rubric:\n{grader.rubric}\n\n"
        f"Original task given to the agent:\n{ctx.case_prompt}\n\n"
        f"Agent's final output:\n{ctx.agent_final_text}\n"
    )
    opts = ClaudeAgentOptions(
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        allowed_tools=[],
        cwd=str(cwd),
        model=grader.model or ctx.model,
        max_turns=2,
        setting_sources=[],
    )
    res = await run_agent(user_msg, opts, timeout_s=60)
    if res.termination != Termination.completed.value:
        return GradeResult(
            "llm_judge", False,
            f"judge {res.termination}: {(res.error or '').strip()}",
        )
    parsed = _parse_judge_output(res.final_text)
    if parsed is None:
        preview = res.final_text[:160].replace("\n", " ")
        return GradeResult("llm_judge", False, f"unparseable judge output: {preview!r}")
    passed, reason = parsed
    return GradeResult("llm_judge", passed, reason[:200])


async def evaluate(
    grader: Grader,
    cwd: Path,
    *,
    context: JudgeContext | None = None,
    judge_fn: JudgeFn | None = None,
) -> GradeResult:
    """Evaluate a single grader, routing llm_judge through the judge callable."""
    if isinstance(grader, LlmJudgeGrader):
        if context is None:
            return GradeResult("llm_judge", False, "no JudgeContext provided")
        fn = judge_fn or _default_judge
        return await fn(grader, cwd, context)
    return evaluate_sync(grader, cwd)
