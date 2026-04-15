# evalbench

An eval harness for Claude agents, built on the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

Each test case becomes a prompt delivered to an isolated Claude subagent
configured with a *system under test* — a skill, a CLI, or a bare system
prompt. After all cases run, evalbench collects per-case metrics (tokens,
turns, tool calls, wall time, pass/fail) and renders a report.

## Status

Early scaffolding. See the build plan in the repo history / PR description.

## Auth

evalbench uses whatever authentication the `claude` CLI is already configured
with on your machine:

- Unset `ANTHROPIC_API_KEY` and run `claude login` once to use your Pro/Max
  subscription.
- Or set `ANTHROPIC_API_KEY` to use API billing.

## Install

```bash
pip install -e '.[dev]'
```

## Usage

```bash
evalbench run    <suite-dir>
evalbench report <run-dir>
evalbench diff   <run-dir> --baseline <run-dir>
```

`run` writes its output to `runs/<timestamp>/` by default:

- `results.jsonl` — one line per (case, trial)
- `meta.json` — run metadata
- `report.md` — auto-generated markdown report

## Example

The repo ships a tiny skill + suite so you can see the bench end-to-end:

```bash
evalbench run cases/hello_example
```

The suite targets `skills/hello/` (a greeting skill), runs two cases —
one purely programmatic, one with an `llm_judge` rubric — and writes a
report when it finishes.

## Suite layout

```
my_suite/
  suite.yaml         # target + run config
  case_foo.yaml      # one file per case
  case_bar.yaml
  fixtures/          # any files referenced by case `fixtures:`
```

## Grader types

- `file_exists { path }`
- `file_contains { path, needle, regex: bool }`
- `shell { command }` — passes iff exit 0 in the case cwd
- `llm_judge { rubric, model? }` — a separate Claude call returns JSON
  `{"passed": bool, "reason": str}`

All graders must pass for a case to pass.

## Targets

- `skill { path, allowed_tools }` — loads `SKILL.md` as system prompt
- `prompt { system_prompt, allowed_tools }` — bare system prompt
- `cli { binary, system_prompt?, allowed_tools }` — exposes a CLI via Bash
