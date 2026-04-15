"""Tests for the markdown report."""

from __future__ import annotations

import json
from pathlib import Path

from evalbench.report import _percentile, load_run, render_markdown, write_report


def _write_run(run_dir: Path, rows: list[dict], meta: dict | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    if meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(meta))
    with (run_dir / "results.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _row(cid="a", trial=1, passed=True, turns=2, tools=1, wall=500,
         inp=100, out=50, termination="completed", error=None, grades=None,
         cost_usd=None) -> dict:
    return {
        "case_id": cid, "trial": trial, "passed": passed,
        "grades": grades or [],
        "tokens": {"input": inp, "output": out, "cache_read": 0, "cache_create": 0},
        "turns": turns, "tool_calls": tools, "wall_ms": wall,
        "termination": termination, "error": error, "cost_usd": cost_usd,
    }


def test_percentile_basic() -> None:
    assert _percentile([], 0.5) == 0.0
    assert _percentile([1.0], 0.95) == 1.0
    assert _percentile([1, 2, 3, 4, 5], 0.5) == 3.0


def test_render_summary_and_table(tmp_path: Path) -> None:
    _write_run(tmp_path, [
        _row("a", 1, True, wall=100, inp=10, out=5),
        _row("b", 1, False, wall=300, inp=20, out=15, termination="timeout",
             error="too slow",
             grades=[{"type": "file_exists", "passed": False, "detail": "missing"}]),
    ], meta={"suite_dir": "/x", "trials": 1, "concurrency": 2,
             "started_at": "20260101T000000"})
    run = load_run(tmp_path)
    md = render_markdown(run)
    assert "1/2" in md  # pass count
    assert "50.0%" in md
    assert "| a | 1 | PASS" in md
    assert "| b | 1 | FAIL" in md
    assert "## Failures" in md
    assert "file_exists" in md
    assert "too slow" in md
    assert "timeout" in md


def test_write_report_roundtrip(tmp_path: Path) -> None:
    _write_run(tmp_path, [_row()], meta={"suite_dir": "/x"})
    out = write_report(tmp_path)
    assert out == tmp_path / "report.md"
    assert "evalbench run report" in out.read_text()


def test_load_run_without_meta(tmp_path: Path) -> None:
    _write_run(tmp_path, [_row()])  # no meta.json
    run = load_run(tmp_path)
    assert run.meta == {}
    assert len(run.results) == 1


def test_cost_na_when_none(tmp_path: Path) -> None:
    _write_run(tmp_path, [_row(cost_usd=None)])
    md = render_markdown(load_run(tmp_path))
    assert "Cost: n/a" in md


def test_cost_labeled_as_list_price_on_subscription(tmp_path: Path) -> None:
    _write_run(tmp_path, [_row(cost_usd=0.01), _row(cost_usd=0.02)],
               meta={"provenance": {"auth_mode": "subscription"}})
    md = render_markdown(load_run(tmp_path))
    assert "$0.0300" in md
    assert "list-price equivalent" in md
    assert "subscription" in md
    # Should NOT claim this was billed.
    assert "Cost (billed)" not in md


def test_cost_labeled_as_billed_on_api_key(tmp_path: Path) -> None:
    _write_run(tmp_path, [_row(cost_usd=0.05)],
               meta={"provenance": {"auth_mode": "api_key"}})
    md = render_markdown(load_run(tmp_path))
    assert "Cost (billed): $0.0500" in md
    assert "list-price" not in md


def test_cost_labeled_unknown_when_auth_mode_missing(tmp_path: Path) -> None:
    _write_run(tmp_path, [_row(cost_usd=0.05)])  # no meta / no provenance
    md = render_markdown(load_run(tmp_path))
    assert "$0.0500" in md
    assert "auth mode unknown" in md
