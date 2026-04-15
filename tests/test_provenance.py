"""Tests for provenance capture."""

from __future__ import annotations

import json
from pathlib import Path

from evalbench.config import load_suite
from evalbench.provenance import collect_static, merge_dynamic


def _write_suite(tmp_path: Path, *, target_kind: str = "prompt") -> Path:
    sd = tmp_path / "s"
    sd.mkdir()
    if target_kind == "prompt":
        (sd / "suite.yaml").write_text(
            "target:\n  type: prompt\n  system_prompt: hi\n"
        )
    elif target_kind == "skill":
        skill_dir = tmp_path / "skills" / "x"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# skill body")
        (sd / "suite.yaml").write_text(
            "target:\n  type: skill\n  path: ../skills/x\n"
        )
    elif target_kind == "cli":
        (sd / "suite.yaml").write_text(
            "target:\n  type: cli\n  binary: mytool\n"
        )
    (sd / "case_a.yaml").write_text("id: a\nprompt: p1\n")
    (sd / "case_b.yaml").write_text("id: b\nprompt: p2\n")
    return sd


def test_collect_static_prompt_target(tmp_path: Path) -> None:
    suite = load_suite(_write_suite(tmp_path, target_kind="prompt"))
    info = collect_static(suite)
    assert info["sdk_version"]
    assert info["python_version"]
    assert info["platform"]
    assert info["target"]["kind"] == "prompt"
    assert len(info["target"]["system_prompt_sha256"]) == 64
    assert set(info["case_hashes"]) == {"a", "b"}
    # All hashes are 64-char hex.
    assert all(len(h) == 64 for h in info["case_hashes"].values())


def test_collect_static_skill_target_hashes_skill_md(tmp_path: Path) -> None:
    suite = load_suite(_write_suite(tmp_path, target_kind="skill"))
    info = collect_static(suite)
    assert info["target"]["kind"] == "skill"
    assert len(info["target"]["skill_md_sha256"]) == 64


def test_collect_static_cli_target_records_binary(tmp_path: Path) -> None:
    suite = load_suite(_write_suite(tmp_path, target_kind="cli"))
    info = collect_static(suite)
    assert info["target"]["kind"] == "cli"
    assert info["target"]["binary"] == "mytool"


def test_target_hash_changes_when_system_prompt_changes(tmp_path: Path) -> None:
    one = tmp_path / "one"
    one.mkdir()
    s1 = _write_suite(one, target_kind="prompt")
    suite1 = load_suite(s1)
    h1 = collect_static(suite1)["target"]["system_prompt_sha256"]

    # Change the system_prompt, reload.
    (s1 / "suite.yaml").write_text(
        "target:\n  type: prompt\n  system_prompt: bye\n"
    )
    h2 = collect_static(load_suite(s1))["target"]["system_prompt_sha256"]
    assert h1 != h2


def test_merge_dynamic_aggregates_from_results(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    with results.open("w") as f:
        for row in [
            {"case_id": "a", "termination": "completed", "cost_usd": 0.01,
             "rate_limit_attempts": 0},
            {"case_id": "b", "termination": "error", "cost_usd": 0.02,
             "rate_limit_attempts": 2},
            {"case_id": "c", "termination": "completed", "cost_usd": None,
             "rate_limit_attempts": 1},
        ]:
            f.write(json.dumps(row) + "\n")
    dyn = merge_dynamic(results)
    assert dyn["trials_recorded"] == 3
    assert dyn["terminations"] == {"completed": 2, "error": 1}
    assert abs((dyn["total_cost_usd"] or 0) - 0.03) < 1e-9
    assert dyn["rate_limit_retries_total"] == 3


def test_merge_dynamic_missing_file_returns_zero(tmp_path: Path) -> None:
    assert merge_dynamic(tmp_path / "nope.jsonl")["trials_recorded"] == 0
