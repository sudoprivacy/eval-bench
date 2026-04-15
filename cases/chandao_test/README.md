# chandao-test live suite

Live-exercise suite for the `chandao-test` skill (testcase +
testtask) against a real chandao backend.

## Prerequisites

Same as `cases/chandao_product/README.md`:
- `chandao-cli` installed at `/home/user/chandao-cli`.
- `CHANDAO_BASE_URL` / `CHANDAO_ACCOUNT` / `CHANDAO_PASSWORD` in env.
- A product with id `7` exists on the server.

## Cases

| Case                           | Blast | Exercises                                |
|--------------------------------|-------|------------------------------------------|
| `testcase_read_list`           | read  | `chandao testcase list --product=7`      |
| `testcase_write_create`        | write | `chandao testcase create …` + id capture |
| `testcase_write_update_title`  | write | `chandao testcase update <id> --title=…` |
| `testcase_write_delete_roundtrip` | write | `create` → `delete` → list-absence verify |
| `testtask_read_list`           | read  | `chandao testtask list`                  |
| `testtask_write_create`        | write | testtask create against a seeded build, recovering from a skill that claims testtask is read-only |

The full CRUD-plus-schedule arc covers a realistic QA journey:
orient to existing specs (`testcase_read_list`) → author a new
spec (`testcase_write_create`) → edit it (`testcase_write_update_title`)
→ retire an obsolete one (`testcase_write_delete_roundtrip`) →
audit past rounds (`testtask_read_list`) → schedule a new round
(`testtask_write_create`).

## Skill-drift signal: `testtask_write_create`

The `chandao-test` SKILL.md currently describes `testtask` as
list/get only and tells the agent to fall back to the
`chandao api call POST /api.php?m=testtask&f=create` escape
hatch. In practice `chandao testtask` has grown a proper `create`
subcommand, and the legacy-API form returns `PARAM_CODE_MISSING`
without extra request-shaping. This case tests whether the agent
verifies the skill's claim against `chandao testtask --help`
before committing — a genuinely useful capability when
documentation lags the CLI.

The case's `setup:` seeds a project → execution → build chain
and writes the build id to `build_id.txt` so the agent can focus
on the test-task-creation step (not the delivery chain that
`chandao-delivery` would cover).

## Known coverage gaps

- `testtask_write_update` / `testtask_write_delete` use the same
  legacy two-step confirm-URL pattern as testtask delete; adding
  them would exercise the same "chase the okURL" mechanics the
  setup of `testtask_write_create` already demonstrates, so
  they've been deferred.
- Test-run *execution* and *result recording* aren't exposed by
  the `chandao-test` skill today, so the bench doesn't cover them.
