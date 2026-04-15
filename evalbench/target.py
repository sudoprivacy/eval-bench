"""SUT (system-under-test) target data models and runtime adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal, Union

from claude_agent_sdk import ClaudeAgentOptions
from pydantic import BaseModel, Field


class SkillTarget(BaseModel):
    """Evaluate a skill: a directory containing `SKILL.md` and helpers."""

    type: Literal["skill"] = "skill"
    path: str = Field(..., description="Path to the skill directory (relative to suite).")
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Write", "Bash"])
    # Extra directories to expose via `add_dirs` (e.g. a sibling skill
    # this one references via `Read ../shared/SKILL.md`). Paths are
    # resolved relative to the suite dir.
    extra_add_dirs: list[str] = Field(default_factory=list)


class PromptTarget(BaseModel):
    """Evaluate a bare system prompt with no bundled skill files."""

    type: Literal["prompt"] = "prompt"
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)


class CliTarget(BaseModel):
    """Evaluate an agent that should drive a specific CLI binary."""

    type: Literal["cli"] = "cli"
    binary: str = Field(..., description="CLI the agent is expected to invoke.")
    system_prompt: str | None = Field(
        default=None,
        description="Optional system-prompt snippet describing the CLI.",
    )
    allowed_tools: list[str] = Field(default_factory=lambda: ["Bash"])


Target = Annotated[
    Union[SkillTarget, PromptTarget, CliTarget],
    Field(discriminator="type"),
]


class TargetBuildError(Exception):
    """Raised when a target cannot be realized into agent options."""


def build_options(
    target: Target,
    *,
    suite_dir: Path,
    cwd: Path,
    model: str | None = None,
    max_turns: int | None = None,
) -> ClaudeAgentOptions:
    """Translate a `Target` into `ClaudeAgentOptions` for the runner.

    `suite_dir` is the directory the suite.yaml lives in; used to resolve
    relative paths (e.g. a skill path). `cwd` is the per-case working
    directory the agent runs in.
    """
    if isinstance(target, SkillTarget):
        skill_path = (suite_dir / target.path).resolve()
        if not skill_path.is_dir():
            raise TargetBuildError(f"skill path is not a directory: {skill_path}")
        skill_md = skill_path / "SKILL.md"
        if not skill_md.is_file():
            raise TargetBuildError(f"skill is missing SKILL.md: {skill_md}")
        system_prompt = skill_md.read_text()
        allowed_tools = list(target.allowed_tools)
        add_dirs = [skill_path]
        for extra in target.extra_add_dirs:
            extra_path = (suite_dir / extra).resolve()
            if not extra_path.is_dir():
                raise TargetBuildError(
                    f"extra_add_dirs entry is not a directory: {extra_path}"
                )
            add_dirs.append(extra_path)
    elif isinstance(target, PromptTarget):
        system_prompt = target.system_prompt
        allowed_tools = list(target.allowed_tools)
        add_dirs = []
    elif isinstance(target, CliTarget):
        system_prompt = (
            target.system_prompt
            if target.system_prompt is not None
            else f"You have access to the `{target.binary}` CLI via the Bash tool."
        )
        allowed_tools = list(target.allowed_tools)
        add_dirs = []
    else:  # pragma: no cover — discriminated union exhausts this
        raise TargetBuildError(f"unknown target type: {type(target).__name__}")

    # Agent's Bash tool inherits this env. We forward the parent
    # process's env (so task-relevant vars like CHANDAO_* or proxy
    # config reach the CLI) but prepend cwd to PATH so case-local
    # CLI shims drop in naturally. Hermeticity against Claude Code's
    # ambient context is enforced separately via `setting_sources=[]`.
    env = dict(os.environ)
    env["PATH"] = f"{cwd}:{env.get('PATH', '')}"

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        cwd=str(cwd),
        add_dirs=add_dirs,
        model=model,
        max_turns=max_turns,
        env=env,
        # Hermetic: don't inherit the user's ~/.claude or project CLAUDE.md,
        # which would otherwise leak context into every eval and make
        # pass/fail depend on whoever ran the suite.
        setting_sources=[],
    )
