# chandao-work live suite

Live-exercise suite for the `chandao-work` skill (story + task +
bug) against a real chandao backend.

## Prerequisites

Same as `cases/chandao_product/README.md`:
- `chandao-cli` installed at `/home/user/chandao-cli` (or fix the
  hardcoded path in `suite.yaml`).
- `CHANDAO_BASE_URL` / `CHANDAO_ACCOUNT` / `CHANDAO_PASSWORD` in env.
- A product with id `7` exists on the server (the `chandao_product`
  suite's `product_write_create` leaves one behind that we re-use).

## Cases

Naming: `<object>_<blast>_<verb>[_<variant>].yaml`. See the top-level
`cases/README.md` for the convention and filter patterns.

| Case                  | Blast | Exercises                                |
|-----------------------|-------|------------------------------------------|
| `story_read_list`     | read  | `chandao story list --product=7`         |
| `story_write_create`  | write | `chandao story create …` + id capture    |
| `bug_read_list`       | read  | `chandao bug list --product=7`           |
| `bug_write_create`    | write | `chandao bug create --openedBuild=trunk …` |

## Known coverage gaps

Task cases (`task start|finish|effort|close`) need an Execution,
which needs a Project. The sandbox starts with zero projects, and
`chandao project create` isn't documented in the delivery skill
well enough for the agent to succeed from scratch, so task cases
are deferred until the upstream skill is strengthened.
