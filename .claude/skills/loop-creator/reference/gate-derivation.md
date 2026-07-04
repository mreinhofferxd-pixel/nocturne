# Gate derivation (v1)

The quality gate is the whole safety model. Derive it by precedence and write the
result as an ordered command list into `.loop/loop.config.json` under `"gate"`.

## Precedence (first that yields commands wins)

1. **CI config** — highest fidelity to "what the team considers passing".
   Read `.github/workflows/*.yml` (and `.gitlab-ci.yml`). Extract the run steps
   verbatim — the lint / typecheck / test commands the team already trusts.
2. **Package scripts** — if no usable CI, compose from declared scripts:
   `package.json` scripts (`lint`, `typecheck`, `test`), `Makefile` targets,
   `pyproject.toml` / `tox.ini` sections.
3. **Language defaults** — if neither, fall back to the ecosystem default below.

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

- **Prefer fewer, faster commands.** The gate runs every attempt; a 10-minute
  gate makes the loop crawl.
- **No network-flaky steps** in the gate if avoidable.
- **No tests at all?** Do not synthesize a green-by-vacuum gate. Make the first
  backlog task "scaffold a minimal test harness + one smoke test", then the gate
  has something real to enforce.
- Store the final list verbatim in `loop.config.json`; the orchestrator runs it
  exactly, independently, after every attempt (trust-but-verify).
