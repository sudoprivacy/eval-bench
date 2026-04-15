# chandao-test live suite

Live-exercise suite for the `chandao-test` skill (testcase +
testtask) against a real chandao backend.

## Prerequisites

Same as `cases/chandao_product/README.md`:
- `chandao-cli` installed at `/home/user/chandao-cli`.
- `CHANDAO_BASE_URL` / `CHANDAO_ACCOUNT` / `CHANDAO_PASSWORD` in env.
- A product with id `7` exists on the server.

## Cases

| Case                    | Blast | Exercises                              |
|-------------------------|-------|----------------------------------------|
| `testcase_read_list`    | read  | `chandao testcase list --product=7`    |
| `testcase_write_create` | write | `chandao testcase create …` + id capture |
| `testtask_read_list`    | read  | `chandao testtask list`                |

## Known coverage gaps

The skill itself notes that test-task *creation* requires the
legacy API escape hatch (`chandao api call POST …`). That case
would test agent judgment on when to drop down to `api call`,
which is worth adding once we've validated the basic CRUD cases
are stable.
