# chandao-product live suite

Live-exercise suite for the `chandao-product` skill from
`sudoprivacy/chandao-cli` against a real chandao backend. Unlike
`cases/hello_example`, this suite talks to an external service and
therefore has prerequisites that the bench itself can't provide.

## Prerequisites

1. **`chandao-cli` installed** (the skill under test lives in that repo):
   ```bash
   git clone https://github.com/sudoprivacy/chandao-cli.git /home/user/chandao-cli
   cd /home/user/chandao-cli && pip install -e .
   ```
   Note: `suite.yaml` currently hardcodes `/home/user/chandao-cli/...`.
   Move the checkout or update the paths in `suite.yaml` to match.

2. **A reachable chandao server** and a user account on it.

3. **Credentials in the env of whoever runs `evalbench`**:
   ```bash
   export CHANDAO_BASE_URL='https://<your-chandao-server>/'
   export CHANDAO_ACCOUNT='<user>'
   export CHANDAO_PASSWORD='<password>'
   evalbench run cases/chandao_product
   ```
   Evalbench forwards the parent env to the agent's Bash tool, so
   these vars reach `chandao` inside each case.

## Case layout

Cases live under `cases/` as one YAML per test. Filename *is* the
case id, and follows the convention:

```
<object>_<blast>_<verb>[_<variant>].yaml
```

| axis   | values                                  | purpose                                  |
|--------|-----------------------------------------|------------------------------------------|
| object | `product`, `productplan`                | groups by API object / CLI command group |
| blast  | `read` / `write`                        | `write` mutates server state             |
| verb   | `list`, `get`, `create`, `update`, …    | matches CLI subcommand                   |

That lets you slice with the existing `--filter`:

```bash
# Safe against prod — read-only cases only
evalbench run cases/chandao_product --filter '*_read_*'

# Just the Product object (skip productplan)
evalbench run cases/chandao_product --filter 'product_*'

# Everything
evalbench run cases/chandao_product
```

## Cases today

| Case                                 | Blast | Exercises                                   |
|--------------------------------------|-------|---------------------------------------------|
| `product_read_list`                  | read  | `chandao product list` + summarize count    |
| `product_write_create`               | write | `product create`, capture returned id       |
| `product_write_update_name`          | write | `product update <id> --name=…`, verify      |
| `product_write_delete_roundtrip`     | write | `create` → `delete` → list-absence verify   |

Each write case is idempotent: its `setup:` deletes any sentinel
from a prior run before the agent starts, so the agent exercises
the real create/update/delete path, not the duplicate-recovery one.

## Grading pattern

Write cases follow a three-layer grade:

1. **`file_exists`** — did the agent produce an answer file at all.
2. **`shell`** (deterministic) — post-condition check via a
   follow-up CLI call. The server, not just the answer file, must
   reflect the intended state.
3. **`llm_judge`** — semantic check of the transcript (did the
   agent actually call the expected commands, or did it fake the
   answer?). Judges that need ground truth get `tools: [Read, Glob,
   Grep, Bash]` so they can re-hit the API.

## Notes

- `suite.yaml` pins `concurrency: 1` — writes against a shared
  server can't safely run in parallel (the create/delete sentinels
  would collide across cases).
- The skill references a sibling `chandao-shared/SKILL.md` via
  Read; `suite.yaml` exposes that via `extra_add_dirs`.
- Write cases leave no server state on success: `create` is paired
  with `update`/`delete` cases that also clean up their own
  sentinels. `product_write_create` still leaves one behind (it
  has no paired delete) — run `chandao product delete <id>` if
  you care.
