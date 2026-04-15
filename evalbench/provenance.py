"""Collect metadata needed to trust and reproduce an eval run.

Without this, a diff between two runs can quietly compare different
SDK versions, different underlying models, or different skill files.
Everything we reasonably can capture goes into `meta.json` so a run
is self-describing months later.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import claude_agent_sdk

from .config import Suite
from .target import CliTarget, PromptTarget, SkillTarget


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _claude_cli_version() -> str | None:
    """Return `claude --version` output, or None if not available."""
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _case_hashes(suite: Suite) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in suite.cases:
        if c.source_path is not None and c.source_path.exists():
            out[c.id] = _sha256_bytes(c.source_path.read_bytes())
    return out


def _target_hash(suite: Suite) -> dict[str, Any]:
    """Hash the SUT so a diff between runs catches accidental drift."""
    target = suite.target
    if isinstance(target, SkillTarget):
        assert suite.source_dir is not None
        skill_md = (suite.source_dir / target.path).resolve() / "SKILL.md"
        if skill_md.exists():
            return {
                "kind": "skill",
                "skill_md_sha256": _sha256_bytes(skill_md.read_bytes()),
                "path": str(skill_md),
            }
        return {"kind": "skill", "skill_md_sha256": None, "path": str(skill_md)}
    if isinstance(target, PromptTarget):
        return {
            "kind": "prompt",
            "system_prompt_sha256": _sha256_bytes(target.system_prompt.encode()),
        }
    if isinstance(target, CliTarget):
        blob = target.binary + "\n" + (target.system_prompt or "")
        return {"kind": "cli", "binary": target.binary,
                "config_sha256": _sha256_bytes(blob.encode())}
    return {"kind": "unknown"}


def collect_static(suite: Suite) -> dict[str, Any]:
    """Collect provenance that doesn't depend on runtime results."""
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "sdk_version": getattr(claude_agent_sdk, "__version__", None),
        "claude_cli_version": _claude_cli_version(),
        # "api_key" when billed per token; "subscription" when the
        # `claude` CLI is OAuth-logged-in to a Pro/Max plan. Affects
        # how `cost_usd` should be interpreted in reports.
        "auth_mode": "api_key" if os.environ.get("ANTHROPIC_API_KEY") else "subscription",
        "target": _target_hash(suite),
        "case_hashes": _case_hashes(suite),
    }


def merge_dynamic(results_path: Path) -> dict[str, Any]:
    """Derive dynamic provenance from a completed run's JSONL.

    For now that's just the distinct set of terminations, the total
    recorded cost (if any), and the first result's trial so you can
    tell whether a run aborted partway.
    """
    import json
    results: list[dict[str, Any]] = []
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not results:
        return {"trials_recorded": 0}

    terminations: dict[str, int] = {}
    for r in results:
        terminations[r.get("termination", "unknown")] = (
            terminations.get(r.get("termination", "unknown"), 0) + 1
        )
    costs = [r.get("cost_usd") for r in results if r.get("cost_usd") is not None]
    rate_retries = sum(int(r.get("rate_limit_attempts") or 0) for r in results)

    return {
        "trials_recorded": len(results),
        "terminations": terminations,
        "total_cost_usd": sum(costs) if costs else None,
        "rate_limit_retries_total": rate_retries,
    }
