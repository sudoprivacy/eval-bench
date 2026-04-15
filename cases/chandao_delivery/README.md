# chandao-delivery live suite

Live-exercise suite for the `chandao-delivery` skill (project +
execution + build + release). **Read-only for now.**

## Prerequisites

Same as `cases/chandao_product/README.md`:
- `chandao-cli` installed at `/home/user/chandao-cli`.
- `CHANDAO_BASE_URL` / `CHANDAO_ACCOUNT` / `CHANDAO_PASSWORD` in env.
- A product with id `7` exists (re-used across the chandao suites).

## Cases

| Case                  | Blast | Exercises                        |
|-----------------------|-------|----------------------------------|
| `project_read_list`   | read  | `chandao project list`           |
| `release_read_list`   | read  | `chandao release list --product=7` |

## Why no write cases yet

`chandao project create` requires undocumented fields that the
skill's SKILL.md doesn't expose to the agent (`-F products=<id>`,
`--hasProduct=1`, `--begin`, `--end`). A write case would either:

1. Fail (exposing a skill doc gap, which is useful but not a "green
   suite"); or
2. Leak the undocumented form into the prompt (defeats the point —
   we'd be testing our prompt, not the skill).

Preferred path: strengthen `chandao-cli/skills/chandao-delivery/SKILL.md`
with a `project create` reference first, then add
`project_write_create_delete_roundtrip` here. Same shape applies to
`execution` and `build`.
