"""Case model and YAML loader."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from .grade import Grader


class Limits(BaseModel):
    max_turns: int = 20
    timeout_s: int = 120


class Case(BaseModel):
    """A single eval test case."""

    id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    setup: list[str] = Field(
        default_factory=list,
        description="Shell commands executed in the case cwd before the agent starts.",
    )
    fixtures: list[str] = Field(
        default_factory=list,
        description="Paths (relative to suite dir) copied into the case cwd.",
    )
    limits: Limits = Field(default_factory=Limits)
    grade: list[Grader] = Field(default_factory=list)

    # Explicit list of files (relative to cwd) to pass to llm_judge graders
    # as evidence. `None` means auto-discover (bounded snapshot of cwd);
    # `[]` means send no files — only the agent's spoken reply.
    judge_evidence: list[str] | None = None

    # Populated by the loader so the runner can resolve relative paths.
    source_path: Path | None = None


class CaseLoadError(Exception):
    """Raised when a case YAML fails to load or validate."""


def load_case(path: Path) -> Case:
    """Load a single case YAML file."""
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise CaseLoadError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise CaseLoadError(f"{path}: expected a mapping at top level")
    try:
        case = Case.model_validate(data)
    except ValidationError as e:
        raise CaseLoadError(f"{path}: {e}") from e
    case.source_path = path
    return case


def load_cases_from_dir(suite_dir: Path) -> list[Case]:
    """Load every `case_*.yaml` (or `cases/*.yaml`) under a suite dir.

    Accepts either:
      - `<suite>/case_<id>.yaml` files directly in the suite dir, or
      - `<suite>/cases/*.yaml` in a nested directory.
    """
    candidates: list[Path] = []
    candidates.extend(sorted(suite_dir.glob("case_*.yaml")))
    nested = suite_dir / "cases"
    if nested.is_dir():
        candidates.extend(sorted(nested.glob("*.yaml")))

    seen: set[str] = set()
    cases: list[Case] = []
    for path in candidates:
        case = load_case(path)
        if case.id in seen:
            raise CaseLoadError(f"duplicate case id {case.id!r} in {path}")
        seen.add(case.id)
        cases.append(case)
    return cases
