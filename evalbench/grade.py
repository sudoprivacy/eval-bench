"""Grader data models and pass/fail evaluation.

In v1 each grader returns a boolean; a case passes iff *all* its graders
pass. Programmatic graders (file/shell) run synchronously; `llm_judge`
routes through the Claude Agent SDK via an injectable callable.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field as dc_field
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
    # The judge is itself an agent: it can call these tools (scoped to
    # the case cwd) to decide what to inspect. `None` = use the safe
    # read-only default set. `[]` = no tools (preset hint only).
    tools: list[str] | None = None
    max_turns: int = 12
    # Wall-clock budget for the judge. 120s was tight for an agentic
    # judge that shells out to external APIs; 240s is comfortable.
    timeout_s: int = 240


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
    # name -> contents of any files produced/modified by the agent in
    # the case cwd. Populated by the runner. Judge prompts embed these
    # verbatim so a rubric like "is the greeting warm?" can actually
    # read the greeting instead of only the agent's spoken reply.
    evidence_files: dict[str, str] = dc_field(default_factory=dict)


JudgeFn = Callable[["LlmJudgeGrader", Path, JudgeContext], Awaitable[GradeResult]]


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluation judge for an agent's output.\n\n"
    "You receive a rubric, the original task given to the agent, and "
    "the agent's final spoken reply. You are running in the agent's "
    "working directory and have read-only tools (Read, Glob, Grep) to "
    "inspect any files the agent produced or modified. Use them as "
    "needed to verify the rubric — do not rely solely on the agent's "
    "spoken reply, which may not reflect the actual artifacts.\n\n"
    "Your final response must follow the required schema: pass/fail "
    "plus a concise reason. If a rubric condition is not verifiable "
    "from the files or spoken reply, return passed=false."
)

# Default model for llm_judge. We intentionally do NOT fall back to the
# target's model: asking the model we're evaluating to grade itself is
# a recipe for rubber-stamping. Override per-grader via `model:` in the
# rubric YAML, or globally by patching DEFAULT_JUDGE_MODEL.
DEFAULT_JUDGE_MODEL = "claude-opus-4-6"

# Read-only tool set the judge agent gets by default. Intentionally no
# Bash (could mutate files and corrupt later graders) and no Write/Edit.
DEFAULT_JUDGE_TOOLS = ["Read", "Glob", "Grep"]

# JSON schema passed to the SDK's `output_format`. The SDK enforces
# this CLI-side and returns the parsed object in
# ResultMessage.structured_output, so we don't regex-scan free text.
JUDGE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["passed", "reason"],
    "additionalProperties": False,
}


def _format_evidence(files: dict[str, str]) -> str:
    if not files:
        return ""
    parts = ["\nFiles in the working directory after the agent ran:"]
    for name, content in files.items():
        parts.append(f"\n--- file: {name} ---\n{content}\n--- end {name} ---")
    return "\n".join(parts) + "\n"


async def _default_judge(
    grader: "LlmJudgeGrader", cwd: Path, ctx: JudgeContext,
) -> GradeResult:
    # Imported here to avoid a circular import at module load.
    from .agent import run_agent
    from .metrics import Termination

    evidence_hint = _format_evidence(ctx.evidence_files)
    if evidence_hint:
        evidence_hint = (
            "\nThe runner has pre-loaded these file contents as a hint "
            "(you may still Read any other files yourself):\n"
            + evidence_hint
        )

    user_msg = (
        f"Rubric:\n{grader.rubric}\n\n"
        f"Original task given to the agent:\n{ctx.case_prompt}\n\n"
        f"Agent's final spoken reply:\n{ctx.agent_final_text}\n"
        f"{evidence_hint}\n"
        "Inspect the working directory as needed, then emit your JSON verdict."
    )
    tools = (DEFAULT_JUDGE_TOOLS if grader.tools is None
             else list(grader.tools))
    opts = ClaudeAgentOptions(
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        allowed_tools=tools,
        cwd=str(cwd),
        # Judge model is independent of the target's model. See
        # DEFAULT_JUDGE_MODEL comment for rationale.
        model=grader.model or DEFAULT_JUDGE_MODEL,
        max_turns=grader.max_turns,
        setting_sources=[],
        # Force the final assistant message to conform to this schema —
        # the SDK parses it for us and returns the dict in
        # result.structured_output.
        output_format={"type": "json_schema", "schema": JUDGE_OUTPUT_SCHEMA},
    )
    res = await run_agent(user_msg, opts, timeout_s=grader.timeout_s)
    if res.termination != Termination.completed.value:
        return GradeResult(
            "llm_judge", False,
            f"judge {res.termination}: {(res.error or '').strip()}",
        )

    # The SDK's json_schema enforcement gives us a validated dict.
    # Anything else is a judge-infrastructure failure, not a grader
    # result — surface it explicitly.
    out = res.structured_output
    if not isinstance(out, dict) or "passed" not in out:
        return GradeResult(
            "llm_judge", False,
            f"judge returned no structured_output: {type(out).__name__}",
        )
    return GradeResult(
        "llm_judge", bool(out["passed"]), str(out.get("reason", ""))[:200],
    )


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
