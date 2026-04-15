"""Validate the bundled example suite loads and builds agent options."""

from __future__ import annotations

from pathlib import Path

from evalbench.config import load_suite
from evalbench.target import SkillTarget, build_options

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "cases" / "hello_example"


def test_example_suite_loads() -> None:
    suite = load_suite(EXAMPLE_DIR)
    assert isinstance(suite.target, SkillTarget)
    ids = sorted(c.id for c in suite.cases)
    assert ids == ["greet-ada", "greet-colleague"]
    assert suite.run.trials == 1
    # The llm_judge rubric in the second case parses into an LlmJudgeGrader.
    collegue = [c for c in suite.cases if c.id == "greet-colleague"][0]
    assert any(g.type == "llm_judge" for g in collegue.grade)


def test_example_skill_build_options(tmp_path: Path) -> None:
    suite = load_suite(EXAMPLE_DIR)
    opts = build_options(
        suite.target,
        suite_dir=EXAMPLE_DIR,
        cwd=tmp_path,
    )
    # SKILL.md content becomes the system prompt.
    assert opts.system_prompt is not None
    assert "Hello skill" in opts.system_prompt
    assert "Write" in opts.allowed_tools
