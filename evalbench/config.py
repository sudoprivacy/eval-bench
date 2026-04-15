"""Suite configuration model and loader.

A suite lives in a directory containing:
  - `suite.yaml`  (run config + target)
  - `case_*.yaml` or `cases/*.yaml` (one file per test case)
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from .case import Case, load_cases_from_dir
from .target import Target


class RunConfig(BaseModel):
    concurrency: int = Field(default=5, ge=1)
    trials: int = Field(default=1, ge=1)
    model: str | None = None


class Suite(BaseModel):
    target: Target
    run: RunConfig = Field(default_factory=RunConfig)

    # Populated by the loader.
    source_dir: Path | None = None
    cases: list[Case] = Field(default_factory=list)


class SuiteLoadError(Exception):
    """Raised when a suite YAML fails to load or validate."""


def load_suite(suite_dir: Path) -> Suite:
    """Load a suite: its `suite.yaml` plus all cases."""
    suite_yaml = suite_dir / "suite.yaml"
    if not suite_yaml.exists():
        raise SuiteLoadError(f"{suite_dir}: missing suite.yaml")

    try:
        data = yaml.safe_load(suite_yaml.read_text())
    except yaml.YAMLError as e:
        raise SuiteLoadError(f"{suite_yaml}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SuiteLoadError(f"{suite_yaml}: expected a mapping at top level")

    try:
        suite = Suite.model_validate(data)
    except ValidationError as e:
        raise SuiteLoadError(f"{suite_yaml}: {e}") from e

    suite.source_dir = suite_dir
    suite.cases = load_cases_from_dir(suite_dir)
    if not suite.cases:
        raise SuiteLoadError(f"{suite_dir}: no cases found")
    return suite
