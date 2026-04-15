# AGENT.md

Guidance for agents (human or AI) working on this repo.

## What this is

`evalbench` is a harness for evaluating Claude agents — skills, system
prompts, or CLI-backed agents — under a suite of reproducible YAML
test cases. It spawns one Claude subagent per (case, trial) via the
Claude Agent SDK, grades the output (programmatic assertions +
optional LLM judge), and renders a markdown report. A diff command
compares two runs for regression.

## Non-negotiable decisions (don't revisit without discussion)

| Decision | Rationale |
|---|---|
| Substrate: Claude **Agent SDK** (Python) | Only path that exposes per-subagent usage/steps. |
| Auth: **subscription** (`claude login`) preferred | No `ANTHROPIC_API_KEY` required. Runs inherit OAuth from the CLI. |
| SUT types: **Skill, Prompt, CLI** | No MCP targets (explicit scope). |
| Isolation: **per-case tempdir** | No Docker. Cases + skills are trusted. |
| Grade output: **pass/fail boolean** per case | All graders must pass. No weighted scoring in v1. |
| Trials default: **1** | Pin to ≥3 for official runs where variance matters. |
| Comparison: **first-class diff** | `evalbench diff` is day-one, not an afterthought. |

## Architecture at a glance

```
 suite.yaml + case_*.yaml                       ← YAML, pydantic-validated
          │
          ▼
  evalbench.config.load_suite(dir)
          │
          ▼
  evalbench.runner.run_suite()
    ├─ semaphore-bounded asyncio.gather
    └─ per (case, trial):
         ├─ tempdir + fixtures + setup shell
         ├─ target.build_options() → ClaudeAgentOptions
         ├─ <env>Working directory: …</env> + case.prompt
         ├─ agent.run_agent() → AgentRunResult
         ├─ grade.evaluate() per grader
         └─ append JSONL line under lock
          │
          ▼
  runs/<ts>/results.jsonl + meta.json + report.md
          │
          ▼
  evalbench.report / evalbench.diff
```

## Module map

| File | Responsibility |
|---|---|
| `evalbench/cli.py` | Click entry: `run / report / diff`. |
| `evalbench/case.py` | `Case` model, `load_case`, `load_cases_from_dir`. |
| `evalbench/config.py` | `Suite`, `RunConfig`, `load_suite`. |
| `evalbench/target.py` | `Skill/Prompt/CliTarget` + `build_options()`. |
| `evalbench/grade.py` | Grader types + sync evaluator + async `llm_judge`. |
| `evalbench/agent.py` | `run_agent()` — drives SDK `query()`, extracts metrics. |
| `evalbench/runner.py` | Per-case pipeline + `run_suite()` with parallelism. |
| `evalbench/metrics.py` | `CaseResult`, `TokenUsage`, `GradeRecord` dataclasses. |
| `evalbench/report.py` | `results.jsonl` → `report.md`. |
| `evalbench/diff.py` | Two runs → `diff.md`. |

## Gotchas you will hit

These are load-bearing and easy to break. Read before touching the
runner or target modules.

1. **Hermeticity via `setting_sources=[]`** — every `ClaudeAgentOptions`
   passes `setting_sources=[]`. Removing this will cause the subprocess
   to pick up the invoking user's `~/.claude/` and the project's
   `CLAUDE.md`, making eval results depend on who ran them. If you need
   per-run overrides, add a case/suite-level opt-in; **do not** flip
   the default.

2. **cwd envelope is mandatory** — disabling `setting_sources` also
   disables Claude Code's `<env>` block, so the agent has no idea what
   cwd is. `runner.run_case_trial` prepends an `<env>Working directory:
   …</env>` header to the user prompt. Without this, the model
   hallucinates paths (observed: `/Users/user/greeting.txt`) and the
   suite turns into noise.

3. **Post-ResultMessage stream exceptions are normal** — the SDK
   sometimes raises after yielding a valid `ResultMessage` (subprocess
   teardown). `agent._drive` tracks `got_result` and silently absorbs
   those exceptions. Don't "simplify" by removing that flag.

4. **Termination classification uses `subtype`, not `stop_reason`** —
   `stop_reason` can be `"end_turn"` on a `subtype="error_max_turns"`
   run. Prefer `subtype`.

5. **`num_turns` counts user + assistant** — a simple Q→A is 2 turns.
   Set `max_turns` ≥ 4 for any case that involves a tool call.

6. **Judge ≠ target** — `llm_judge` uses `grader.model or ctx.model`.
   For serious evals, pin the judge model explicitly in the grader
   config and make it at least as strong as the target.

7. **`llm_judge` output parsing is lenient** — `_parse_judge_output`
   accepts the first JSON object in the reply. If you change the
   judge system prompt, keep the `{"passed": bool, "reason": str}`
   contract or update the parser.

## Conventions

- **Python 3.11+**, `from __future__ import annotations` everywhere.
- **Pydantic v2** for config models; dataclasses for result/metric types.
- **Async tests**: `pytest-asyncio`, `asyncio_mode = "auto"` (set in `pyproject.toml`).
- **No real SDK calls in tests** — inject `agent_fn` / `judge_fn`. If
  you need to change this rule, a file like `tests/live/` gated by
  a marker is acceptable; live tests must never run by default.
- **Keep the CLI thin** — business logic stays in modules, not Click
  callbacks.
- **No documentation files outside** `README.md` and this `AGENT.md`
  unless the user explicitly asks.

## Suite & case schemas

See `README.md` for the public version. Quick reference:

```yaml
# suite.yaml
target:
  type: skill | prompt | cli
  # type-specific fields: path | system_prompt | binary
  allowed_tools: [Read, Write, Bash, ...]
run:
  concurrency: 5
  trials: 1
  model: claude-sonnet-4-6   # pin this for comparable runs
```

```yaml
# case_*.yaml
id: <unique-id>
prompt: "..."
setup: ["shell cmd in cwd", ...]
fixtures: [paths relative to suite dir, copied into cwd]
limits: { max_turns: 20, timeout_s: 120 }
grade:
  - type: file_exists | file_contains | shell | llm_judge
    # type-specific fields
```

## Run artifacts

```
runs/<YYYYMMDDThhmmss>/
  meta.json       suite path, trials, concurrency, model, started_at
  results.jsonl   one JSON per (case, trial)
  report.md       auto-rendered at end of `run`
  diff.md         written by `evalbench diff` (when used)
```

## Running the pipeline

```bash
# dev loop
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q

# live smoke (requires `claude login`)
evalbench run cases/hello_example
evalbench diff runs/<new> --baseline runs/<old>
```

## When tests won't cover you

The following paths don't have CI-runnable tests and rely on live
smoke:

- SDK stream-teardown exception behavior (`agent._drive`'s
  `got_result` flag).
- Rate-limit events from the subscription.
- Real `llm_judge` output format.

If you change any of these paths, run `evalbench run cases/hello_example`
manually and inspect `results.jsonl`. A two-case suite is ~$0.10.

## What to push back on

- **"Just remove `setting_sources=[]`"** — see gotcha #1.
- **"Use Docker for isolation"** — explicitly out of scope. If you
  think we need it, raise it as a decision, don't just add it.
- **"Add retries/backoff around every SDK call"** — we currently
  surface rate limits as errors so they're visible. Retry logic is
  worth having but needs a design, not a sprinkling.
- **"Make the judge lenient/strict by editing the prompt"** — calibrate
  first. A judge whose own pass/fail isn't measured isn't a grader, it's
  a coin flip.

## Open robustness gaps (as of this writing)

Done:

- ✅ Subprocess cleanup on timeout/cancel — `ClaudeSDKClient` used as async
  context manager so the `claude` subprocess is disconnected on exit
  (`agent.py::_drive`).
- ✅ Rate-limit backoff — `RateLimitEvent.status == "rejected"` aborts the
  attempt and `run_agent` retries with exponential backoff; count
  surfaces as `rate_limit_attempts` in `CaseResult`.
- ✅ Provenance in `meta.json` — `provenance.collect_static` captures SDK
  version, `claude --version`, Python/platform, SKILL.md hash, per-case
  hashes; `merge_dynamic` aggregates terminations/cost/retries post-run.
- ✅ Per-case transcripts — written to
  `runs/<ts>/transcripts/<case>-t<trial>.jsonl` with assistant text,
  tool uses, tool results, rate-limit events, and retry markers.
- ✅ Judge model separate from target — `grade.DEFAULT_JUDGE_MODEL`
  (currently `claude-opus-4-6`); never falls back to `ctx.model`.
- ✅ `schema_version` field on `CaseResult` (forward-compat insurance).

Still open:

1. **`HOME` isolation per case.** Subprocesses share `$HOME`; the SDK
   writes to `~/.claude/sessions/`. Concurrent runs could collide.
2. **Suite-level budget caps.** `--max-cost-usd N` / `--max-wall-s N`
   with early abort.
3. **`evalbench debug <suite> <case-id>`.** Streams assistant text and
   tool calls to stdout in real time; `--keep-failed` + cat tempdir is
   too many steps.
4. **Judge calibration.** `evalbench calibrate <suite>` that runs the
   judge against known-good and known-bad reference outputs and reports
   precision/recall.
5. **Global adaptive concurrency.** When rate-limit warnings fire,
   halve the semaphore for the rest of the run.
6. **Catastrophic-regex guard** in `file_contains` graders.
7. **Lenient JSONL loader** that skips malformed lines with a warning.
