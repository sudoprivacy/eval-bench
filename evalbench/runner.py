"""Per-case execution: temp-dir setup, agent invocation, grading, JSONL output."""

from __future__ import annotations

import asyncio
import fnmatch
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
from .grade import JudgeContext, JudgeFn, evaluate
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


async def _grade_case(
    case: Case, cwd: Path, ctx: JudgeContext,
    judge_fn: JudgeFn | None,
) -> list[GradeRecord]:
    out: list[GradeRecord] = []
    for g in case.grade:
        r = await evaluate(g, cwd, context=ctx, judge_fn=judge_fn)
        out.append(GradeRecord(type=r.type, passed=r.passed, detail=r.detail))
    return out


def _count_rate_limit_attempts(transcript: list[dict]) -> int:
    """Number of retries that happened (0 = succeeded first try)."""
    return sum(1 for e in transcript if e.get("kind") == "retry_marker")


def _write_transcript(dir_: Path, case_id: str, trial: int,
                      transcript: list[dict]) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{case_id}-t{trial}.jsonl"
    with path.open("w") as f:
        for entry in transcript:
            json.dump(entry, f, default=str)
            f.write("\n")
    return path


async def run_case_trial(
    case: Case,
    suite: Suite,
    trial: int,
    *,
    keep_failed: bool = False,
    agent_fn: AgentFn | None = None,
    judge_fn: JudgeFn | None = None,
    transcript_dir: Path | None = None,
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

        # With `setting_sources=[]` (hermetic mode) Claude Code no longer
        # injects its normal <env> block — so the model has no idea what
        # cwd is and will hallucinate one. Explicitly tell it.
        framed_prompt = (
            f"<env>\nWorking directory: {cwd}\n"
            "All file paths must be absolute (under the working directory) "
            "or relative to it. Do not write to or read paths outside this "
            "directory.\n</env>\n\n"
            f"{case.prompt}"
        )

        fn = agent_fn or _default
        agent = await fn(framed_prompt, opts)

        judge_ctx = JudgeContext(
            case_prompt=case.prompt,
            agent_final_text=agent.final_text,
            model=suite.run.model,
        )
        grades = await _grade_case(case, cwd, judge_ctx, judge_fn)
        passed = (
            agent.termination == Termination.completed.value
            and all(g.passed for g in grades)
        )

        transcript_path: str | None = None
        if transcript_dir is not None and agent.transcript:
            p = _write_transcript(
                transcript_dir, case.id, trial, agent.transcript,
            )
            transcript_path = str(p)

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
            rate_limit_attempts=_count_rate_limit_attempts(agent.transcript),
            transcript_path=transcript_path,
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


ResultHook = Callable[[CaseResult], None]


async def run_suite(
    suite: Suite,
    results_path: Path,
    *,
    filter_glob: str | None = None,
    keep_failed: bool = False,
    agent_fn: AgentFn | None = None,
    judge_fn: JudgeFn | None = None,
    on_result: ResultHook | None = None,
    transcript_dir: Path | None = None,
) -> list[CaseResult]:
    """Execute every (case, trial) pair with bounded concurrency.

    Writes each result to `results_path` as a JSON line as soon as it
    completes, behind an asyncio lock so concurrent appends don't
    interleave. `on_result` fires from inside the same lock, which
    makes it safe to use for ordered progress printing.
    """
    cases = [
        c for c in suite.cases
        if not filter_glob or fnmatch.fnmatch(c.id, filter_glob)
    ]
    if not cases:
        return []

    sem = asyncio.Semaphore(suite.run.concurrency)
    write_lock = asyncio.Lock()
    results: list[CaseResult] = []

    async def _one(case: Case, trial: int) -> CaseResult:
        async with sem:
            result = await run_case_trial(
                case, suite, trial,
                keep_failed=keep_failed,
                agent_fn=agent_fn,
                judge_fn=judge_fn,
                transcript_dir=transcript_dir,
            )
        async with write_lock:
            append_jsonl(results_path, result)
            results.append(result)
            if on_result is not None:
                on_result(result)
        return result

    tasks = [
        _one(case, trial)
        for case in cases
        for trial in range(1, suite.run.trials + 1)
    ]
    await asyncio.gather(*tasks)
    return results
