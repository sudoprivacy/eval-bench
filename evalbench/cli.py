"""Command-line entry point for evalbench."""

from __future__ import annotations

import asyncio
import datetime as dt
import fnmatch
import json
from pathlib import Path

import click

from . import __version__
from .config import load_suite
from .diff import write_diff
from .report import write_report
from .runner import run_suite


@click.group()
@click.version_option(__version__)
def main() -> None:
    """evalbench — an eval harness for Claude agents."""


@main.command()
@click.argument("suite_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--concurrency", type=int, default=None, help="Override suite concurrency.")
@click.option("--trials", type=int, default=None, help="Override trials per case.")
@click.option("--filter", "filter_glob", type=str, default=None, help="Glob over case IDs.")
@click.option("--keep-failed", is_flag=True, help="Keep temp dirs for failing cases.")
@click.option("--runs-dir", type=click.Path(file_okay=False), default="runs",
              help="Directory to write run outputs into.")
def run(suite_dir: str, concurrency: int | None, trials: int | None,
        filter_glob: str | None, keep_failed: bool, runs_dir: str) -> None:
    """Run a suite of eval cases."""
    asyncio.run(_run_async(
        suite_dir=suite_dir,
        concurrency=concurrency,
        trials=trials,
        filter_glob=filter_glob,
        keep_failed=keep_failed,
        runs_dir=runs_dir,
    ))


async def _run_async(
    *,
    suite_dir: str,
    concurrency: int | None,
    trials: int | None,
    filter_glob: str | None,
    keep_failed: bool,
    runs_dir: str,
) -> None:
    suite = load_suite(Path(suite_dir))
    if trials is not None:
        suite.run.trials = trials
    if concurrency is not None:
        suite.run.concurrency = concurrency

    cases = [
        c for c in suite.cases
        if not filter_glob or fnmatch.fnmatch(c.id, filter_glob)
    ]
    if not cases:
        raise click.ClickException(f"no cases match filter: {filter_glob!r}")

    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = Path(runs_dir) / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    (run_dir / "meta.json").write_text(json.dumps({
        "suite_dir": str(Path(suite_dir).resolve()),
        "trials": suite.run.trials,
        "concurrency": suite.run.concurrency,
        "model": suite.run.model,
        "started_at": stamp,
    }, indent=2))

    total = len(cases) * suite.run.trials
    counter = {"done": 0, "ok": 0}

    def _on_result(result) -> None:  # type: ignore[no-untyped-def]
        counter["done"] += 1
        counter["ok"] += int(result.passed)
        tag = "PASS" if result.passed else "FAIL"
        extra = f" [{result.termination}]" if result.termination != "completed" else ""
        click.echo(
            f"[{counter['done']:>3}/{total}] {tag}{extra} {result.case_id} "
            f"t{result.trial} turns={result.turns} tools={result.tool_calls} "
            f"wall_ms={result.wall_ms}"
        )

    try:
        await run_suite(
            suite, results_path,
            filter_glob=filter_glob, keep_failed=keep_failed,
            on_result=_on_result,
            transcript_dir=run_dir / "transcripts",
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        # The async-with inside each agent call already disconnects
        # subprocesses cleanly; report whatever we managed to write.
        click.echo("\ninterrupted — partial results retained", err=True)

    report_path = write_report(run_dir)
    click.echo(f"\n{counter['ok']}/{total} passed → {results_path}")
    click.echo(f"report → {report_path}")


@main.command()
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
def report(run_dir: str) -> None:
    """Render a markdown report from a run's results.jsonl."""
    path = write_report(Path(run_dir))
    click.echo(f"wrote {path}")


@main.command()
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--baseline", type=click.Path(exists=True, file_okay=False), required=True,
              help="Baseline run directory to diff against.")
def diff(run_dir: str, baseline: str) -> None:
    """Diff a run against a baseline run."""
    path = write_diff(Path(run_dir), Path(baseline))
    click.echo(f"wrote {path}")


if __name__ == "__main__":
    main()
