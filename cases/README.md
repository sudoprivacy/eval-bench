# cases/

One directory per suite. A suite binds one skill (or prompt/CLI
target) to a set of cases that exercise it.

```
cases/
  hello_example/        # framework smoke (2 cases)
  chandao_product/      # skill: chandao-product   (4 cases)
  chandao_work/         # skill: chandao-work      (4 cases)
  chandao_delivery/     # skill: chandao-delivery  (2 cases, read-only)
  chandao_test/         # skill: chandao-test      (6 cases)
```

Inside each suite:

```
<suite>/
  suite.yaml            # target + run config
  README.md             # prerequisites + case table
  cases/
    <case>.yaml         # one per test
```

## Case naming: `<object>_<blast>_<verb>[_<variant>].yaml`

Filename *is* the case id. Three axes encoded:

| axis   | values                              | purpose                                  |
|--------|-------------------------------------|------------------------------------------|
| object | `product`, `story`, `bug`, `task`, … | groups by API object / CLI command group |
| blast  | `read` / `write`                    | `write` mutates server state             |
| verb   | `list`, `get`, `create`, `update`, … | matches CLI subcommand                   |

## Filter patterns

`evalbench run` accepts `--filter <glob>` over case ids, so the
naming convention gives free slicing:

```bash
# Safe against prod — read-only cases across every chandao suite
for s in cases/chandao_*; do
  evalbench run "$s" --filter '*_read_*'
done

# Just the story object
evalbench run cases/chandao_work --filter 'story_*'

# Everything in one suite
evalbench run cases/chandao_product
```

## Grading pattern

Write cases follow a three-layer grade:

1. **`file_exists`** — did the agent produce an answer file.
2. **`shell`** (deterministic) — post-condition check via a
   follow-up CLI call. The server's state, not just the answer
   file, must reflect the intended change.
3. **`llm_judge`** — observation-level semantic check against the
   cwd files the agent produced + the agent's spoken reply.

   **Rubric rule**: only ask the judge to verify things it can
   actually observe. The judge's default tools are `Read / Glob /
   Grep` scoped to the case cwd; it does NOT see the bash
   transcript. Rubrics that ask "did the agent run command X with
   flag Y?" make the judge wander looking for evidence it can't
   find — and hit its `max_turns` cap. For that shape, rely on a
   `shell` post-condition instead.

   If the judge does need to hit an external API for ground
   truth (e.g. "re-run `chandao X list` and compare to answer.txt"),
   give it `tools: [Read, Glob, Grep, Bash]` explicitly.

## Idempotent setup

Write cases' `setup:` block deletes any sentinel from a prior run
before the agent starts, so the agent always exercises the real
create/update/delete path — never the "already exists" recovery
path. This means suites are safe to re-run.
