"""Tests for target -> ClaudeAgentOptions translation."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalbench.target import (
    CliTarget,
    PromptTarget,
    SkillTarget,
    TargetBuildError,
    build_options,
)


def test_build_options_skill_reads_skill_md(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    skill_dir = tmp_path / "skills" / "hello"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# hello\nBe polite.")
    cwd = tmp_path / "work"
    cwd.mkdir()

    target = SkillTarget(path="../skills/hello", allowed_tools=["Read", "Bash"])
    opts = build_options(
        target, suite_dir=suite_dir, cwd=cwd,
        model="claude-sonnet-4-6", max_turns=7,
    )
    assert opts.system_prompt == "# hello\nBe polite."
    assert opts.allowed_tools == ["Read", "Bash"]
    assert opts.cwd == str(cwd)
    assert opts.add_dirs == [skill_dir.resolve()]
    assert opts.model == "claude-sonnet-4-6"
    assert opts.max_turns == 7


def test_build_options_skill_missing_dir(tmp_path: Path) -> None:
    target = SkillTarget(path="nope")
    with pytest.raises(TargetBuildError, match="not a directory"):
        build_options(target, suite_dir=tmp_path, cwd=tmp_path)


def test_build_options_skill_missing_skill_md(tmp_path: Path) -> None:
    (tmp_path / "skill").mkdir()
    target = SkillTarget(path="skill")
    with pytest.raises(TargetBuildError, match="SKILL.md"):
        build_options(target, suite_dir=tmp_path, cwd=tmp_path)


def test_build_options_prompt(tmp_path: Path) -> None:
    target = PromptTarget(system_prompt="hi", allowed_tools=["Read"])
    opts = build_options(target, suite_dir=tmp_path, cwd=tmp_path)
    assert opts.system_prompt == "hi"
    assert opts.allowed_tools == ["Read"]
    assert opts.add_dirs == []


def test_build_options_cli_default_prompt(tmp_path: Path) -> None:
    target = CliTarget(binary="mytool")
    opts = build_options(target, suite_dir=tmp_path, cwd=tmp_path)
    assert "mytool" in (opts.system_prompt or "")
    assert opts.allowed_tools == ["Bash"]


def test_build_options_cli_custom_prompt(tmp_path: Path) -> None:
    target = CliTarget(binary="mytool", system_prompt="Use mytool to X.")
    opts = build_options(target, suite_dir=tmp_path, cwd=tmp_path)
    assert opts.system_prompt == "Use mytool to X."
