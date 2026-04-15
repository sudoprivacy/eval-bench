"""Command-line entry point for evalbench."""

from __future__ import annotations

import click

from . import __version__


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
def run(suite_dir: str, concurrency: int | None, trials: int | None,
        filter_glob: str | None, keep_failed: bool) -> None:
    """Run a suite of eval cases."""
    click.echo(f"[stub] run suite={suite_dir} concurrency={concurrency} "
               f"trials={trials} filter={filter_glob} keep_failed={keep_failed}")


@main.command()
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
def report(run_dir: str) -> None:
    """Render a markdown report from a run's results.jsonl."""
    click.echo(f"[stub] report run={run_dir}")


@main.command()
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--baseline", type=click.Path(exists=True, file_okay=False), required=True,
              help="Baseline run directory to diff against.")
def diff(run_dir: str, baseline: str) -> None:
    """Diff a run against a baseline run."""
    click.echo(f"[stub] diff run={run_dir} baseline={baseline}")


if __name__ == "__main__":
    main()
