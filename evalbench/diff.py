"""Compare two runs and render a regression report."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

from .report import RunData, load_run


@dataclass
class CaseAggregate:
    case_id: str
    trials: int
    passed: int            # trials that passed
    pass_rate: float
    wall_ms_mean: float
    turns_mean: float
    tool_calls_mean: float
    tokens_in_mean: float
    tokens_out_mean: float

    @property
    def any_pass(self) -> bool:
        return self.passed > 0

    @property
    def all_pass(self) -> bool:
        return self.passed == self.trials


def _aggregate(results: list[dict]) -> dict[str, CaseAggregate]:
    by_id: dict[str, list[dict]] = {}
    for r in results:
        by_id.setdefault(r["case_id"], []).append(r)

    out: dict[str, CaseAggregate] = {}
    for cid, rows in by_id.items():
        n = len(rows)
        passed = sum(1 for r in rows if r.get("passed"))
        wall = [float(r.get("wall_ms") or 0) for r in rows]
        turns = [float(r.get("turns") or 0) for r in rows]
        tools = [float(r.get("tool_calls") or 0) for r in rows]
        tin = [float((r.get("tokens") or {}).get("input", 0)) for r in rows]
        tout = [float((r.get("tokens") or {}).get("output", 0)) for r in rows]
        out[cid] = CaseAggregate(
            case_id=cid, trials=n, passed=passed,
            pass_rate=passed / n,
            wall_ms_mean=statistics.mean(wall),
            turns_mean=statistics.mean(turns),
            tool_calls_mean=statistics.mean(tools),
            tokens_in_mean=statistics.mean(tin),
            tokens_out_mean=statistics.mean(tout),
        )
    return out


def _pct(new: float, old: float) -> str:
    if old == 0:
        return "—" if new == 0 else "+∞%"
    delta = (new - old) / old * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}%"


def _delta(new: float, old: float, fmt: str = ".0f") -> str:
    d = new - old
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:{fmt}} ({_pct(new, old)})"


def classify(baseline: CaseAggregate | None,
             current: CaseAggregate | None) -> str:
    if baseline is None and current is not None:
        return "new"
    if baseline is not None and current is None:
        return "removed"
    assert baseline is not None and current is not None
    if baseline.all_pass and not current.all_pass:
        return "regression"
    if not baseline.all_pass and current.all_pass:
        return "improvement"
    if baseline.pass_rate > current.pass_rate:
        return "regression"
    if baseline.pass_rate < current.pass_rate:
        return "improvement"
    return "same"


def render_diff(baseline: RunData, current: RunData) -> str:
    b = _aggregate(baseline.results)
    c = _aggregate(current.results)
    all_ids = sorted(set(b) | set(c))

    lines: list[str] = []
    lines.append("# evalbench diff report")
    lines.append("")
    lines.append(f"- Baseline: `{baseline.meta.get('suite_dir', '?')}` "
                 f"({baseline.meta.get('started_at', '?')})")
    lines.append(f"- Current:  `{current.meta.get('suite_dir', '?')}` "
                 f"({current.meta.get('started_at', '?')})")
    lines.append("")

    b_pass = sum(1 for a in b.values() if a.all_pass)
    c_pass = sum(1 for a in c.values() if a.all_pass)
    regressions = [cid for cid in all_ids
                   if classify(b.get(cid), c.get(cid)) == "regression"]
    improvements = [cid for cid in all_ids
                    if classify(b.get(cid), c.get(cid)) == "improvement"]

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Cases fully passing: baseline {b_pass}/{len(b)}, "
                 f"current {c_pass}/{len(c)}")
    lines.append(f"- Regressions: **{len(regressions)}**")
    lines.append(f"- Improvements: **{len(improvements)}**")
    lines.append("")

    lines.append("## Per-case")
    lines.append("")
    lines.append("| Case | Status | Pass | Wall ms Δ | Turns Δ | Tokens in Δ | Tokens out Δ |")
    lines.append("|---|---|---|---|---|---|---|")
    for cid in all_ids:
        bi, ci = b.get(cid), c.get(cid)
        status = classify(bi, ci)
        if bi and ci:
            pass_col = f"{bi.passed}/{bi.trials} → {ci.passed}/{ci.trials}"
            wall = _delta(ci.wall_ms_mean, bi.wall_ms_mean)
            turns = _delta(ci.turns_mean, bi.turns_mean, ".2f")
            tin = _delta(ci.tokens_in_mean, bi.tokens_in_mean)
            tout = _delta(ci.tokens_out_mean, bi.tokens_out_mean)
        elif ci:
            pass_col = f"— → {ci.passed}/{ci.trials}"
            wall = turns = tin = tout = "—"
        else:
            assert bi is not None
            pass_col = f"{bi.passed}/{bi.trials} → —"
            wall = turns = tin = tout = "—"
        lines.append(f"| {cid} | {status} | {pass_col} | {wall} | {turns} | {tin} | {tout} |")
    lines.append("")

    return "\n".join(lines)


def write_diff(run_dir: Path, baseline_dir: Path) -> Path:
    """Render `diff.md` inside `run_dir`. Returns the path."""
    baseline = load_run(baseline_dir)
    current = load_run(run_dir)
    md = render_diff(baseline, current)
    out = run_dir / "diff.md"
    out.write_text(md)
    return out
