"""Tests for judge-evidence collection from the case cwd."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalbench.config import load_suite
from evalbench.runner import (
    _EVIDENCE_MAX_BYTES_PER_FILE,
    _EVIDENCE_MAX_FILES,
    _collect_evidence,
)


def _make_suite_and_case(tmp_path: Path, case_yaml: str):
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text(
        "target:\n  type: prompt\n  system_prompt: hi\n"
    )
    (suite_dir / "case_a.yaml").write_text(case_yaml)
    suite = load_suite(suite_dir)
    return suite.cases[0]


def test_auto_discovers_text_files(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path, "id: a\nprompt: p\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "a.txt").write_text("hello")
    (cwd / "b.txt").write_text("world")

    out = _collect_evidence(case, cwd)
    assert set(out) == {"a.txt", "b.txt"}
    assert out["a.txt"] == "hello"


def test_auto_skips_binary_files(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path, "id: a\nprompt: p\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "text.txt").write_text("ok")
    (cwd / "blob.bin").write_bytes(b"\x89PNG\x00\x01\x02\xff")

    out = _collect_evidence(case, cwd)
    assert "text.txt" in out
    assert "blob.bin" not in out


def test_auto_skips_hidden_files(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path, "id: a\nprompt: p\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".hidden").write_text("secret")
    (cwd / "visible.txt").write_text("ok")

    out = _collect_evidence(case, cwd)
    assert set(out) == {"visible.txt"}


def test_auto_respects_file_count_limit(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path, "id: a\nprompt: p\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    for i in range(_EVIDENCE_MAX_FILES + 5):
        (cwd / f"f{i:02d}.txt").write_text(f"n{i}")
    out = _collect_evidence(case, cwd)
    assert len(out) == _EVIDENCE_MAX_FILES


def test_auto_truncates_huge_file(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path, "id: a\nprompt: p\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    huge = "A" * (_EVIDENCE_MAX_BYTES_PER_FILE + 100)
    (cwd / "big.txt").write_text(huge)
    out = _collect_evidence(case, cwd)
    assert "big.txt" in out
    assert len(out["big.txt"]) <= _EVIDENCE_MAX_BYTES_PER_FILE + 50
    assert "truncated" in out["big.txt"]


def test_explicit_list_reads_only_named(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path,
        "id: a\nprompt: p\njudge_evidence: [wanted.txt]\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "wanted.txt").write_text("W")
    (cwd / "unwanted.txt").write_text("U")

    out = _collect_evidence(case, cwd)
    assert set(out) == {"wanted.txt"}
    assert out["wanted.txt"] == "W"


def test_explicit_empty_list_means_no_evidence(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path,
        "id: a\nprompt: p\njudge_evidence: []\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "some.txt").write_text("x")

    out = _collect_evidence(case, cwd)
    assert out == {}


def test_explicit_list_cannot_escape_cwd(tmp_path: Path) -> None:
    """Path traversal must be rejected even if the case asks for it."""
    case = _make_suite_and_case(tmp_path,
        "id: a\nprompt: p\njudge_evidence: ['../secret.txt']\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (tmp_path / "secret.txt").write_text("leak")

    out = _collect_evidence(case, cwd)
    assert out == {}


def test_explicit_list_missing_file_is_skipped(tmp_path: Path) -> None:
    case = _make_suite_and_case(tmp_path,
        "id: a\nprompt: p\njudge_evidence: [a.txt, missing.txt]\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "a.txt").write_text("A")

    out = _collect_evidence(case, cwd)
    assert set(out) == {"a.txt"}
