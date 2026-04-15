"""Tests for YAML case + suite loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalbench.case import CaseLoadError, load_case, load_cases_from_dir
from evalbench.config import SuiteLoadError, load_suite
from evalbench.grade import (
    FileContainsGrader,
    FileExistsGrader,
    LlmJudgeGrader,
    ShellGrader,
)
from evalbench.target import CliTarget, PromptTarget, SkillTarget


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_load_case_minimal(tmp_path: Path) -> None:
    p = _write(tmp_path / "case_min.yaml", "id: a\nprompt: hi\n")
    case = load_case(p)
    assert case.id == "a"
    assert case.prompt == "hi"
    assert case.grade == []
    assert case.limits.max_turns == 20
    assert case.source_path == p


def test_load_case_full_grader_union(tmp_path: Path) -> None:
    p = _write(tmp_path / "case_full.yaml", """
id: full
prompt: do the thing
setup:
  - "echo hello > input.txt"
fixtures:
  - data/sample.csv
limits:
  max_turns: 5
  timeout_s: 30
grade:
  - type: file_exists
    path: output.txt
  - type: file_contains
    path: output.txt
    needle: Ada
    regex: false
  - type: shell
    command: "test -s output.txt"
  - type: llm_judge
    rubric: "Is it polite?"
""")
    case = load_case(p)
    assert len(case.grade) == 4
    assert isinstance(case.grade[0], FileExistsGrader)
    assert isinstance(case.grade[1], FileContainsGrader)
    assert isinstance(case.grade[2], ShellGrader)
    assert isinstance(case.grade[3], LlmJudgeGrader)
    assert case.limits.max_turns == 5


def test_load_case_rejects_missing_id(tmp_path: Path) -> None:
    p = _write(tmp_path / "bad.yaml", "prompt: no id\n")
    with pytest.raises(CaseLoadError):
        load_case(p)


def test_load_case_rejects_unknown_grader(tmp_path: Path) -> None:
    p = _write(tmp_path / "bad.yaml", """
id: x
prompt: hi
grade:
  - type: unknown
    path: foo
""")
    with pytest.raises(CaseLoadError):
        load_case(p)


def test_load_cases_from_dir_flat_and_nested(tmp_path: Path) -> None:
    _write(tmp_path / "case_a.yaml", "id: a\nprompt: x\n")
    (tmp_path / "cases").mkdir()
    _write(tmp_path / "cases" / "b.yaml", "id: b\nprompt: y\n")
    cases = load_cases_from_dir(tmp_path)
    ids = sorted(c.id for c in cases)
    assert ids == ["a", "b"]


def test_load_cases_rejects_duplicate_id(tmp_path: Path) -> None:
    _write(tmp_path / "case_a.yaml", "id: dup\nprompt: x\n")
    _write(tmp_path / "case_b.yaml", "id: dup\nprompt: y\n")
    with pytest.raises(CaseLoadError, match="duplicate"):
        load_cases_from_dir(tmp_path)


def test_load_suite_skill_target(tmp_path: Path) -> None:
    _write(tmp_path / "suite.yaml", """
target:
  type: skill
  path: ../skills/hello
  allowed_tools: [Read, Write]
run:
  concurrency: 3
  trials: 2
""")
    _write(tmp_path / "case_a.yaml", "id: a\nprompt: hi\n")
    suite = load_suite(tmp_path)
    assert isinstance(suite.target, SkillTarget)
    assert suite.target.path == "../skills/hello"
    assert suite.run.concurrency == 3
    assert suite.run.trials == 2
    assert [c.id for c in suite.cases] == ["a"]
    assert suite.source_dir == tmp_path


def test_load_suite_prompt_and_cli_targets(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "p"
    prompt_dir.mkdir()
    _write(prompt_dir / "suite.yaml", """
target:
  type: prompt
  system_prompt: "You are a helper."
""")
    _write(prompt_dir / "case_a.yaml", "id: a\nprompt: hi\n")
    suite = load_suite(prompt_dir)
    assert isinstance(suite.target, PromptTarget)

    cli_dir = tmp_path / "c"
    cli_dir.mkdir()
    _write(cli_dir / "suite.yaml", """
target:
  type: cli
  binary: mytool
""")
    _write(cli_dir / "case_a.yaml", "id: a\nprompt: hi\n")
    suite2 = load_suite(cli_dir)
    assert isinstance(suite2.target, CliTarget)
    assert suite2.target.binary == "mytool"


def test_load_suite_missing_yaml_and_no_cases(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError, match="missing suite.yaml"):
        load_suite(tmp_path)
    _write(tmp_path / "suite.yaml", """
target:
  type: prompt
  system_prompt: hi
""")
    with pytest.raises(SuiteLoadError, match="no cases"):
        load_suite(tmp_path)
