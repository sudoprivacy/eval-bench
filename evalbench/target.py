"""SUT (system-under-test) target data models.

Runtime translation to `ClaudeAgentOptions` lives in a later step; this
module only defines the schema used by suite configs.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class SkillTarget(BaseModel):
    """Evaluate a skill: a directory containing `SKILL.md` and helpers."""

    type: Literal["skill"] = "skill"
    path: str = Field(..., description="Path to the skill directory (relative to suite).")
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Write", "Bash"])


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
