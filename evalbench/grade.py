"""Grader data models and pass/fail evaluation.

In v1 each grader returns a boolean; a case passes iff *all* its graders
pass. Runtime evaluation of `LlmJudgeGrader` is wired up in a later step;
here we only define the schema and a synchronous evaluator for the
purely file/shell-based graders.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Union

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
