"""Tests for the diff command."""

from __future__ import annotations

import json
from pathlib import Path

from evalbench.diff import CaseAggregate, _aggregate, classify, render_diff, write_diff
from evalbench.report import RunData, load_run


def _write_run(run_dir: Path, rows: list[dict], meta: dict | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    if meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(meta))
    with (run_dir / "results.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _row(cid="a", trial=1, passed=True, turns=2, tools=1, wall=500,
         inp=100, out=50) -> dict:
    return {
        "case_id": cid, "trial": trial, "passed": passed, "grades": [],
        "tokens": {"input": inp, "output": out,
                   "cache_read": 0, "cache_create": 0},
        "turns": turns, "tool_calls": tools, "wall_ms": wall,
        "termination": "completed" if passed else "error",
        "error": None, "cost_usd": None,
    }


def test_aggregate_groups_trials() -> None:
    agg = _aggregate([
        _row("a", 1, True, wall=100),
        _row("a", 2, False, wall=300),
        _row("b", 1, True, wall=200),
    ])
    assert set(agg) == {"a", "b"}
    assert agg["a"].trials == 2
    assert agg["a"].passed == 1
    assert agg["a"].pass_rate == 0.5
    assert agg["a"].wall_ms_mean == 200
    assert agg["b"].all_pass is True


def test_classify_regression_and_improvement() -> None:
    full = CaseAggregate("x", 1, 1, 1.0, 0, 0, 0, 0, 0)
    none = CaseAggregate("x", 1, 0, 0.0, 0, 0, 0, 0, 0)
    assert classify(full, none) == "regression"
    assert classify(none, full) == "improvement"
    assert classify(full, full) == "same"
    assert classify(None, full) == "new"
    assert classify(full, None) == "removed"


def test_render_diff_highlights_changes(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    curr_dir = tmp_path / "curr"
    _write_run(base_dir, [
        _row("a", 1, True, wall=100, inp=100, out=50),
        _row("b", 1, True, wall=200, inp=80, out=40),
    ], meta={"suite_dir": "/x"})
    _write_run(curr_dir, [
        _row("a", 1, False, wall=150, inp=120, out=60),  # regression
        _row("b", 1, True, wall=180, inp=70, out=30),   # same
        _row("c", 1, True, wall=100, inp=10, out=5),    # new
    ], meta={"suite_dir": "/x"})

    md = render_diff(load_run(base_dir), load_run(curr_dir))
    assert "Regressions: **1**" in md
    assert "| a | regression" in md
    assert "| b | same" in md
    assert "| c | new" in md
    assert "+50" in md  # wall_ms delta for a (150 - 100)


def test_write_diff_roundtrip(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    curr_dir = tmp_path / "curr"
    _write_run(base_dir, [_row()], meta={"suite_dir": "/x"})
    _write_run(curr_dir, [_row()], meta={"suite_dir": "/x"})
    out = write_diff(curr_dir, base_dir)
    assert out == curr_dir / "diff.md"
    assert "evalbench diff report" in out.read_text()
