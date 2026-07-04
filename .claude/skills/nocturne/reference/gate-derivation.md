# Gate derivation (v1)

The quality gate is the whole safety model. Derive it by precedence and write the
result as an ordered command list into `.loop/loop.config.json` under `"gate"`.

## Precedence (first that yields commands wins)

1. **Explicit done-statement** — the team's own words beat every inference.
   Read `CLAUDE.md` / `AGENTS.md` / `CONTRIBUTING.md` for a stated bar
   ("Done = `python -m pytest tests/unit/`", "all changes must pass X").
   Honor it verbatim — even when a linter or a broader suite exists in the
   repo. Cautionary case (symphony): the stated bar was `pytest tests/unit/`;
   `ruff` existed but was baseline-red and NOT the team's gate — a naive
   `ruff && pytest` would have false-blocked every task.
2. **CI config** — highest-fidelity inference when nothing is stated.
   Read `.github/workflows/*.yml` (and `.gitlab-ci.yml`). Extract the run steps
   verbatim — the lint / typecheck / test commands the team already trusts.
3. **Package scripts** — if no usable CI, compose from declared scripts:
   `package.json` scripts (`lint`, `typecheck`, `test`), `Makefile` targets,
   `pyproject.toml` / `tox.ini` sections.
4. **Language defaults** — if none of the above, fall back to the ecosystem
   default below.

Compose in this order, including only stages that exist:
`<install-if-needed> -> lint -> typecheck -> test`

## Language defaults

| Stack | Default gate |
|---|---|
| Node / TS (pnpm) | `pnpm install --frozen-lockfile` · `pnpm lint` · `pnpm typecheck` · `pnpm test` |
| Node / TS (npm)  | `npm ci` · `npm run lint` · `npm run typecheck` · `npm test` |
| Python (uv)      | `uv sync` · `ruff check .` · `mypy .` · `pytest -q` |
| Python (poetry)  | `poetry install` · `ruff check .` · `mypy .` · `pytest -q` |
| Python (pip)     | `ruff check .` · `mypy .` · `pytest -q` |
| Go               | `go vet ./...` · `go test ./...` |
| Rust             | `cargo clippy -- -D warnings` · `cargo test` |

Only include a stage if the tool is actually configured (e.g. skip `typecheck`
if there is no `tsc`/`mypy` config). Skip `install` if deps are already present
and offline install would fail.

## Rules

- **Baseline must be green.** Run the derived gate once BEFORE launch. A red
  baseline means the gate is wrong for this repo (or the repo needs fixing
  first) — do not launch and let the first task inherit pre-existing failures.
  The harness enforces this too (`require_green_baseline`, default true), but
  catching it at derivation time gives the user the better fix loop.
- **Prefer fewer, faster commands.** The gate runs every attempt; a 10-minute
  gate makes the loop crawl.
- **No network-flaky steps** in the gate if avoidable.
- **No tests at all?** Do not synthesize a green-by-vacuum gate. Make the first
  backlog task "scaffold a minimal test harness + one smoke test", then the gate
  has something real to enforce.
- Store the final list verbatim in `loop.config.json`; the orchestrator runs it
  exactly, independently, after every attempt (trust-but-verify).
