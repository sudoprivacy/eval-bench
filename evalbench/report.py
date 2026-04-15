"""Read a run directory and render a markdown report."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunData:
    meta: dict[str, Any]
    results: list[dict[str, Any]]


def load_run(run_dir: Path) -> RunData:
    """Read `meta.json` + `results.jsonl` from a run directory."""
    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())

    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        raise FileNotFoundError(f"no results.jsonl under {run_dir}")
    results: list[dict[str, Any]] = []
    for line in results_path.read_text().splitlines():
        line = line.strip()
        if line:
            results.append(json.loads(line))
    return RunData(meta=meta, results=results)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _tok(r: dict[str, Any]) -> dict[str, int]:
    return r.get("tokens") or {}


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    wall = [float(r.get("wall_ms") or 0) for r in results]
    input_toks = sum(int(_tok(r).get("input", 0)) for r in results)
    output_toks = sum(int(_tok(r).get("output", 0)) for r in results)
    cache_read_toks = sum(int(_tok(r).get("cache_read", 0)) for r in results)
    cache_create_toks = sum(int(_tok(r).get("cache_create", 0)) for r in results)
    tool_calls = sum(int(r.get("tool_calls") or 0) for r in results)
    costs = [r.get("cost_usd") for r in results if r.get("cost_usd") is not None]
    total_cost = sum(costs) if costs else None

    terminations: dict[str, int] = {}
    for r in results:
        terminations[r.get("termination", "unknown")] = (
            terminations.get(r.get("termination", "unknown"), 0) + 1
        )

    return {
        "total": total,
        "passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
        "wall_ms_mean": (statistics.mean(wall) if wall else 0.0),
        "wall_ms_p50": _percentile(wall, 0.5),
        "wall_ms_p95": _percentile(wall, 0.95),
        "tokens_input": input_toks,
        "tokens_output": output_toks,
        "tokens_cache_read": cache_read_toks,
        "tokens_cache_create": cache_create_toks,
        "tool_calls_total": tool_calls,
        "total_cost_usd": total_cost,
        "terminations": terminations,
    }


def render_markdown(run: RunData) -> str:
    s = _summary(run.results)
    meta = run.meta

    lines: list[str] = []
    lines.append("# evalbench run report")
    lines.append("")
    if meta:
        lines.append(f"- Suite: `{meta.get('suite_dir', '?')}`")
        lines.append(f"- Started: {meta.get('started_at', '?')}")
        lines.append(f"- Model: {meta.get('model') or 'default'}")
        lines.append(f"- Trials: {meta.get('trials', '?')}  Concurrency: {meta.get('concurrency', '?')}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Pass rate**: {s['passed']}/{s['total']} "
                 f"({s['pass_rate'] * 100:.1f}%)")
    lines.append(f"- Wall time (ms): mean {s['wall_ms_mean']:.0f}, "
                 f"p50 {s['wall_ms_p50']:.0f}, p95 {s['wall_ms_p95']:.0f}")
    lines.append(f"- Tokens: input {s['tokens_input']}, output {s['tokens_output']}, "
                 f"cache_read {s['tokens_cache_read']}, "
                 f"cache_create {s['tokens_cache_create']}")
    lines.append(f"- Tool calls (total): {s['tool_calls_total']}")
    cost = s["total_cost_usd"]
    auth_mode = (meta.get("provenance") or {}).get("auth_mode")
    if cost is None:
        lines.append("- Cost: n/a")
    elif auth_mode == "subscription":
        lines.append(
            f"- Cost: ~${cost:.4f} (list-price equivalent, not billed — "
            f"subscription auth)"
        )
    elif auth_mode == "api_key":
        lines.append(f"- Cost (billed): ${cost:.4f}")
    else:
        # Unknown auth (old runs without provenance) — be honest about it.
        lines.append(
            f"- Cost: ~${cost:.4f} (auth mode unknown; SDK-reported)"
        )
    if s["terminations"]:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(s["terminations"].items()))
        lines.append(f"- Terminations: {parts}")
    lines.append("")

    lines.append("## Per-trial results")
    lines.append("")
    lines.append(
        "| Case | Trial | Pass | Termination | Turns | Tools | Wall ms | "
        "In tok | Cache R | Cache W | Out tok | Cost USD |"
    )
    lines.append(
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for r in run.results:
        t = _tok(r)
        mark = "PASS" if r.get("passed") else "FAIL"
        cost_val = r.get("cost_usd")
        cost_cell = f"{cost_val:.4f}" if isinstance(cost_val, (int, float)) else "-"
        lines.append(
            f"| {r.get('case_id','?')} | {r.get('trial','?')} | "
            f"{mark} | {r.get('termination','?')} | "
            f"{r.get('turns', 0)} | {r.get('tool_calls', 0)} | "
            f"{r.get('wall_ms', 0)} | "
            f"{t.get('input', 0)} | {t.get('cache_read', 0)} | "
            f"{t.get('cache_create', 0)} | {t.get('output', 0)} | "
            f"{cost_cell} |"
        )
    lines.append("")

    # Failure detail
    failures = [r for r in run.results if not r.get("passed")]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for r in failures:
            lines.append(f"### `{r.get('case_id')}` trial {r.get('trial')}")
            if r.get("error"):
                lines.append(f"- error: `{r['error']}`")
            bad = [g for g in (r.get("grades") or []) if not g.get("passed")]
            if bad:
                lines.append("- failing graders:")
                for g in bad:
                    lines.append(f"  - `{g.get('type')}` — {g.get('detail','')}")
            lines.append("")

    return "\n".join(lines)


def write_report(run_dir: Path) -> Path:
    """Render `report.md` next to `results.jsonl`. Returns the path."""
    run = load_run(run_dir)
    md = render_markdown(run)
    out = run_dir / "report.md"
    out.write_text(md)
    return out
