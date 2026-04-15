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
