"""Per-case execution: temp-dir setup, agent invocation, grading, JSONL output."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from .agent import AgentRunResult, run_agent
from .case import Case
from .config import Suite
from .grade import LlmJudgeGrader, evaluate_sync
from .metrics import CaseResult, GradeRecord, Termination
from .target import build_options

AgentFn = Callable[[str, ClaudeAgentOptions], Awaitable[AgentRunResult]]


class RunnerError(Exception):
    """Raised when case setup (fixtures/setup commands) fails."""


def _prepare_cwd(case: Case, suite: Suite, cwd: Path) -> None:
    if suite.source_dir is None:
        raise RunnerError("suite.source_dir is not set; load via load_suite()")

    for fixture in case.fixtures:
        src = (suite.source_dir / fixture).resolve()
        if not src.exists():
            raise RunnerError(f"case {case.id}: fixture not found: {src}")
        dst = cwd / Path(fixture).name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    for cmd in case.setup:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RunnerError(
                f"case {case.id}: setup command failed: {cmd!r}: "
                f"exit={proc.returncode} stderr={proc.stderr.strip()!r}"
            )


def _grade_case(case: Case, cwd: Path) -> list[GradeRecord]:
    out: list[GradeRecord] = []
    for g in case.grade:
        if isinstance(g, LlmJudgeGrader):
            # Wired up in the grader step; until then, mark as skipped-fail
            # so cases relying on it don't silently pass.
            out.append(GradeRecord(
                type="llm_judge", passed=False,
                detail="llm_judge evaluation not yet implemented",
            ))
            continue
        r = evaluate_sync(g, cwd)
        out.append(GradeRecord(type=r.type, passed=r.passed, detail=r.detail))
    return out


async def run_case_trial(
    case: Case,
    suite: Suite,
    trial: int,
    *,
    keep_failed: bool = False,
    agent_fn: AgentFn | None = None,
) -> CaseResult:
    """Run one trial of one case end-to-end and return the result."""
    assert suite.source_dir is not None
    cwd = Path(tempfile.mkdtemp(prefix=f"evalbench-{case.id}-t{trial}-"))
    result: CaseResult
    try:
        _prepare_cwd(case, suite, cwd)
        opts = build_options(
            suite.target,
            suite_dir=suite.source_dir,
            cwd=cwd,
            model=suite.run.model,
            max_turns=case.limits.max_turns,
        )

        async def _default(p: str, o: ClaudeAgentOptions) -> AgentRunResult:
            return await run_agent(p, o, timeout_s=case.limits.timeout_s)

        fn = agent_fn or _default
        agent = await fn(case.prompt, opts)

        grades = _grade_case(case, cwd)
        passed = (
            agent.termination == Termination.completed.value
            and all(g.passed for g in grades)
        )
        result = CaseResult(
            case_id=case.id,
            trial=trial,
            passed=passed,
            grades=grades,
            tokens=agent.tokens,
            turns=agent.turns,
            tool_calls=agent.tool_calls,
            wall_ms=agent.wall_ms,
            termination=agent.termination,
            error=agent.error,
            cost_usd=agent.cost_usd,
        )
    except Exception as exc:
        result = CaseResult(
            case_id=case.id,
            trial=trial,
            passed=False,
            termination=Termination.error.value,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if result.passed or not keep_failed:
            shutil.rmtree(cwd, ignore_errors=True)
    return result


def append_jsonl(path: Path, result: CaseResult) -> None:
    """Append a single CaseResult as a JSON line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        json.dump(result.to_dict(), f, default=str)
        f.write("\n")
