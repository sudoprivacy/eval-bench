"""Per-case result + token usage data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Termination(str, Enum):
    completed = "completed"
    timeout = "timeout"
    max_turns = "max_turns"
    error = "error"


@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_create: int = 0


@dataclass
class GradeRecord:
    type: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    trial: int
    passed: bool
    grades: list[GradeRecord] = field(default_factory=list)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    turns: int = 0
    tool_calls: int = 0
    wall_ms: int = 0
    termination: str = Termination.completed.value
    error: str | None = None
    cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
