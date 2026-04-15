# chandao-product live suite

A live-exercise suite that evaluates the `chandao-product` skill from
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

## Cases

- **`product-list`** (read-only): list products, report count, judge
  independently verifies by re-running `chandao product list`.
- **`product-create`** (writes server state): create a product, write
  the returned id to a file, verify the product exists via a
  follow-up `chandao product get`.

The `create` case leaves one product behind on the server per run;
delete with `chandao product delete <id>` if you care about cleanup.

## Notes

- The judge for `product-list` uses `tools: [Read, Glob, Grep, Bash]`
  so it can hit the real API for ground-truth comparison.
- The skill references a sibling `chandao-shared/SKILL.md` via Read;
  `suite.yaml` exposes that through `extra_add_dirs` so the agent's
  Read tool can find it.
