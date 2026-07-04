# nocturne — Spec

A Claude Code skill that reads a repository and its backlog, then **generates and launches an optimal headless agentic loop** tailored to that repo's architecture, test setup, and goals. The user fires one command; the skill designs the loop (backlog source, quality gate, git strategy, guardrails, budget), writes the harness, previews it, and starts it.

Two layers of Claude:
- **Design layer** — the interactive Claude running this skill inspects the repo and *authors* the loop.
- **Execution layer** — a headless `claude -p` process that the generated harness drives in a while-loop to actually do the work.

This makes concrete the thing people gesture at ("prompt Claude with Claude, set up a loop") instead of leaving it vague.

---

## 1. Goals & non-goals

**Goals**
- One command turns a repo + backlog into a running, self-verifying dev loop.
- The loop is *derived from the repo*, not a fixed template: it detects stack, test runner, lint/typecheck, CI, monorepo layout, conventions.
- Every iteration is gated by a machine-checkable quality bar. No commit unless the gate is green — verified by the harness, not by the model's self-report.
- Configurable autonomy; **autonomous by default** behind strong guardrails (branch isolation, budget cap, protected paths, stuck-detection).
- Resumable: kill it, restart, it continues from state.
- Observable: per-iteration logs, a live report, halt notifications.

**Design principle — minimal instruction, trust the model.** The models are strong; over-instructing hurts. Generated per-iteration prompts and any `CLAUDE.md` the loop writes stay lean. The loop's value is *structure* the model can't give itself — gate, guardrails, state, verification — not verbose hand-holding. When in doubt, cut prompt text.

**Non-goals**
- Not a CI system. It runs locally/headless; it *reads* CI config to learn the gate.
- Not a replacement for human review of merges to `main` (default keeps `main` untouched).
- Not tied to one language. Stack-specific behavior is detected, not hardcoded.

---

## 2. Feasibility (the headless loop)

A Claude Code skill can ship scripts and run them. The generated harness is a plain loop around headless Claude:

```bash
claude -p "<per-iteration prompt>" \
  --append-system-prompt "$REPO_CONVENTIONS" \
  --output-format stream-json \
  --permission-mode acceptEdits \
  --allowedTools "Edit,Write,Bash,Read,Grep,Glob" \
  --max-turns "$MAX_TURNS" \
  --model claude-opus-4-8
```

The harness — not the model — owns control flow: pick next task, invoke Claude, **independently re-run the gate**, check git for a new commit, decide done/retry/blocked, update state, repeat. `stream-json` output is parsed for token/cost accounting and a run summary.

The skill itself can launch the harness in the background and hand back a monitor command, or hand the user a ready-to-run script — controlled by a flag.

---

## 3. End-to-end flow

```
/nocturne [goal or flags]
        │
        ▼
Phase 0  Preflight        clean worktree? git repo? claude CLI + auth? runtime (bash/node/py)?
Phase 1  Recon            detect stack, test/lint/typecheck, CI commands, monorepo, conventions
Phase 2  Backlog          acquire tasks (markdown | github | interactive-decompose | plugin)
Phase 3  Gate synthesis   build the exact quality-gate command from CI → scripts → defaults
Phase 4  Loop synthesis   generate harness, per-iteration prompt, config, guardrails, git plan
Phase 5  Preview & confirm show plan: backlog, gate, guardrails, est. cost → require GO (once)
Phase 6  Run              launch headless loop; stream logs; update report; halt on done/stuck/budget
Phase 7  Handoff          summary: commits, PRs, blocked tasks, cost, how to resume
```

Autonomy applies to Phase 6. Phase 5 is a one-time human gate (skippable with `--yes` for true unattended runs).

---

## 4. Skill anatomy (files the skill ships)

```
nocturne/
  SKILL.md                     # frontmatter + phase-by-phase instructions for the design-layer Claude
  reference/
    recon-checklist.md         # what to detect and how (per ecosystem)
    gate-derivation.md         # CI → scripts → language-default precedence rules
    prompt-contract.md         # the per-iteration prompt template + output contract
    guardrails.md              # default denylists, protected paths, safety rules
  templates/
    orchestrator.py            # preferred harness (robust stream-json parsing, cost, state)
    loop.sh                    # bash/git-bash fallback harness
    loop.ps1                   # PowerShell fallback (Windows)
    iteration-prompt.tmpl      # filled per task
    loop.config.json.tmpl      # generated config schema
  adapters/
    markdown.py                # BACKLOG.md / TODO.md / PLAN.md checkbox list
    github.py                  # gh issue list/close by label
    interactive.py             # decompose a goal → ordered backlog → writes markdown
    adapter_interface.md       # next_task / mark_done / mark_blocked / list  ("something else" plugs here)
```

The design-layer Claude reads `reference/*`, runs recon, fills `templates/*`, and drops the generated loop into the target repo under `.loop/`.

---

## 5. Phase 1 — Repo reconnaissance

Detect and record into `.loop/recon.json`:

| Dimension | Signals |
|---|---|
| Language / stack | `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, `Gemfile`, `*.csproj` |
| Package manager | lockfiles: `pnpm-lock`, `yarn.lock`, `package-lock`, `bun.lockb`, `uv.lock`, `poetry.lock` |
| Test runner | `scripts.test`, pytest/tox, `go test`, `cargo test`, jest/vitest config |
| Lint / format | eslint, biome, ruff, prettier, gofmt, clippy, rubocop |
| Typecheck | `tsc`, mypy, pyright |
| **CI commands** | `.github/workflows/*`, `.gitlab-ci.yml` — *extracted verbatim; this is the gate's source of truth* |
| Build | build scripts, Makefile targets |
| Monorepo | workspaces, turbo/nx/lerna, cargo workspaces → per-package scoping |
| Conventions | `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, commit-message style |
| Git state | default branch, remote present, worktree clean, protected branches |
| Remote host | origin URL → github/gitlab → enables the matching issue adapter + PR/MR auto-open, and `gh`/`glab` presence |
| Runtime available | python3 / node presence → picks orchestrator vs shell harness |
| Test presence | if none found → flag to scaffold a minimal test harness before looping |

Monorepo: recon produces a package map; the loop scopes each task to its package and runs only that package's gate for speed.

---

## 6. Phase 2 — Backlog acquisition (pluggable adapters)

All adapters implement one interface so new sources ("something else") drop in without touching the harness:

```
next_task()            -> {id, title, body, acceptance?, package?} | None
mark_done(task, sha)   -> void   # check box / close issue / comment link
mark_blocked(task, why)-> void
list()                 -> [tasks with status]
```

Bundled adapters (base set):
- **markdown** — parses checkbox lists in `BACKLOG.md` / `TODO.md` / `PLAN.md`. Unchecked = todo; checks off + records commit on done. Self-contained, git-tracked, zero external deps. *Default.*
- **github** — `gh issue list --label loop`, closes issue + comments the commit/PR link on done. Needs `gh` auth.
- **gitlab** — `glab issue list` by label, closes + comments on done. Needs `glab` auth.
- **interactive** — user gives a high-level goal; the design-layer Claude decomposes it into an **ordered, dependency-aware backlog** of small, independently-verifiable, single-commit-sized tasks, writes it to `BACKLOG.md`, then converges to the markdown adapter.
- **plugin** — any file implementing the interface. This is the extension point for later sources (Linear / Jira / Notion / a DB / an API) — not built now, but the interface guarantees they slot in without touching the harness.

**Units (independently-mergeable clusters):** grooming groups tasks into ordered *units* by dependency — a unit is the smallest set of tasks that can merge on its own. Independent tickets are their own single-task units; a dependency chain collapses into one unit. Units drive PR granularity and unit-checkpointing (§8.3, §9). Adapters map naturally: markdown headings = units with checkboxes as tasks; GitHub milestone/label = unit; interactive decomposition emits unit groups, not a flat list. No grouping in the source → whole backlog is one unit.

**Grooming step:** before looping, the design layer splits oversized items and flags ambiguous ones for the preview so the loop never starts on a vague mega-task.

---

## 7. Phase 3 — Quality-gate synthesis

Gate command is derived by precedence (see `reference/gate-derivation.md`):

1. **CI config** — reproduce the exact command sequence CI runs (highest fidelity to "what the team considers passing").
2. **Package scripts** — e.g. `lint` + `typecheck` + `test` targets if present.
3. **Language defaults** — `ruff && mypy && pytest`, `tsc && vitest`, `go vet && go test ./...`, `cargo clippy && cargo test`, etc.

Result stored as an explicit, ordered command list in `loop.config.json`. Recommended composition (auto-detect from repo, per your Q4 choice), applied as available:

```
<install-if-needed> → lint → typecheck → test  (scoped to touched package in monorepos)
```

TDD is applied *selectively*, not globally: for logic-bearing tasks the per-iteration prompt instructs write-failing-test-first; for mechanical/config tasks it doesn't, to avoid churn. If recon finds **no tests at all**, the first synthesized task is "scaffold a minimal test harness + one smoke test" so the gate has something to enforce.

---

## 8. Phase 4 — The generated loop

### 8.1 Control flow (harness owns it)

```
load state (.loop/state.json)
while not (backlog empty or budget hit or consecutive_blocked ≥ MAX_BLOCKED):
    task = adapter.next_task()
    for attempt in 1..MAX_RETRIES:
        run claude -p <iteration prompt(task, gate, conventions, prior failure?)>
        gate_result = run gate  ← harness re-runs it; model self-report NOT trusted
        new_commit = git detected a new commit this attempt?
        if gate_result.green and new_commit:
            adapter.mark_done(task, sha); log; break
        else:
            failure_ctx = gate_result.output (tail) + diff summary
            if no_progress(diff == last_diff):  break  # stuck, stop wasting budget
    if not done:
        adapter.mark_blocked(task, reason); consecutive_blocked += 1
    else:
        consecutive_blocked = 0
    checkpoint state; update report
emit halt reason + summary; notify
```

Key discipline: **trust-but-verify.** The model may claim success; the harness independently runs the gate and checks git before marking done.

### 8.2 Per-iteration prompt contract (`reference/prompt-contract.md`)

Each headless call is given exactly:
- **One task** + acceptance criteria (never the whole backlog — keeps scope tight).
- Repo conventions via `--append-system-prompt` (from `CLAUDE.md` + recon).
- The **exact gate command** and the instruction: "make this pass."
- Constraints: stay in task scope; don't touch protected paths; one small commit with a conventional message; TDD-first for logic tasks.
- **Output contract:** end with a parseable status line (`STATUS: done|blocked`, `REASON: ...`) — used as a hint, not as ground truth.

### 8.3 Git strategy

- Work on a dedicated branch `loop/<timestamp>` (never `main` by default).
- One commit per completed task, conventional-commit message, task id in trailer.
- **Dependency-aware PRs (default).** The unit of a PR is the **smallest independently-mergeable cluster of tasks** (§6): independent tickets each get their own draft PR; a real dependency chain (task 2 needs task 1) becomes one PR. Each unit branches off the **default branch**, so no unit is ever based on another unit's *unapproved* code — independent by construction. Within a unit, tasks stack (inherent to dependent work) and are reviewed together as one coherent PR.
- Draft PR opens when the last task in a unit lands (github/gitlab remote + `gh`/`glab` present). Human reviews and merges. If a unit unavoidably sits on an unmerged sibling, the PR body notes **"based on unmerged #X."**
- Push only when PRs are enabled or `--push` is set. **Never force-push. Never merge to the default branch autonomously.** `--pr-per none` disables; `--pr-per task --stack` opts into stacked per-task PRs (PR N based on PR N-1) for the fully-dependent case.

### 8.4 Per-task model tiering

The loop picks the model per task by complexity — cheap where possible, opus where it matters.

Default tier map (cheap → expensive):

| Complexity | Model | Typical tasks |
|---|---|---|
| simple | `claude-sonnet-5` | routine feature/bugfix, single-module logic, mechanical edits |
| medium / complex *(default)* | `claude-opus-4-8` | most work — architecture, multi-file logic, anything ambiguous |
| very complex | `claude-fable-5` | only the hardest tasks — reserved because it's the priciest tier; not used unless a task is tagged very-complex or the model is explicitly requested |

How a task gets its tier (first that applies):
1. **Explicit** — `model` or `complexity` set on the task (from config or backlog tag). Only path that reaches `fable-5` by default.
2. **Tagged at decomposition** — the design-layer Claude labels each task `simple|complex|very-complex` while grooming; label → model.
3. **Cheap triage** — if still untagged, a one-line `claude-sonnet-5` call rates it; unresolved → falls to the default (`opus-4-8`).

**Retry escalation:** if a task fails its gate on a cheaper tier, the next retry escalates one tier (`sonnet-5 → opus-4-8 → fable-5`). Cheap-first, climb only when needed. Any tier is overridable per task and globally in config.

---

### 8.5 Gate integrity (anti-gaming)

The gate is the whole safety model, so the loop actively defends it against the cheapest-path failure: passing the gate by **weakening the gate** instead of solving the task. After each iteration the harness runs a **diff-guard** before accepting a commit:

- **Coverage-reducing edits are rejected** (attempt counts as failed) when the diff touches test files, gate/lint/type config, or CI and does so in a suppressing way — removed/relaxed assertions, new `skip`/`only`/`xit`/`todo`, added `@ts-ignore` / `eslint-disable` / `# type: ignore` / `# noqa`, loosened coverage thresholds, or disabled rules — **unless** the current task is explicitly tagged `modifies-tests` / `refactor-tests` (guard relaxed for that task only).
- **Ratchet** — test count and coverage % are recorded in `.loop/state.json`. The gate additionally requires `tests_after ≥ tests_before` and `coverage_after ≥ coverage_before`. Monotonic non-decreasing; the loop can never quietly shrink the suite.
- **Flag, don't hide** — any diff that touches the gate surface (even when green and allowed) is surfaced in `.loop/report.md` for human review, with the specific lines called out.

Net: "green" alone is never sufficient — green **and** a non-suppressing diff **and** a non-shrinking suite. This is what makes trust-but-verify actually trustworthy.

### 8.6 Task acceptance (done ≠ gate-green)

The generic gate proves "the suite passes," not "this task's intent was met." An honest-but-wrong implementation can pass a weak self-written test. So **done** requires a task-specific acceptance test, not just a green suite:

- **Acceptance authored at decomposition** — every task carries an `acceptance` field: the concrete, machine-checkable test (or exact command + expected result) that passes *only if the intent is met*. Grooming rejects tasks that lack one.
- **Acceptance-test-first** — for such tasks the per-iteration prompt writes/registers the acceptance test **before** implementation (red → green). The harness verifies this specific test exists and passes, on top of the full gate — a green suite that doesn't include the task's acceptance test is *not* done.
- **Non-codifiable tasks are refused by auto-mode** — if a task's success genuinely can't be expressed as a test (UX feel, subjective copy, a design judgment), auto-mode does not guess. It **routes the task to a human checkpoint** and continues with the rest of the backlog. Auto-mode only auto-completes tasks with a codifiable acceptance.
- **Acceptance is anti-gameable too** — the §8.5 diff-guard treats the task's own acceptance test as protected: it can be *added* but not weakened/skipped within the same task.

Definition of done, fully: **full gate green + the task's acceptance test present-and-passing + non-suppressing, non-shrinking diff + new commit.**

### 8.7 Scope-drift handling (near-zero cost)

Scoping is owned up front by the human/decomposition, not re-checked by the working agent. Two cheap backstops catch drift:

- **Mechanical oversize guard** — the harness already has the diff and retry count, so no extra tokens: if an attempt's diff exceeds a file-count threshold or retries exhaust without the gate converging, the task is blocked with reason **"likely too large — split needed"** (actionable), not a bare "failed."
- **Forward-flag** — the agent that *just finished* a task appends one line if it invalidated a later task's premise (e.g. "changed the User model shape"). Next-task selection surfaces it. The *current* working agent never re-validates scope.

## 9. Autonomy & guardrails (configurable, autonomous default)

Modes via `--mode`:
- `auto` (**default**) — runs unattended; stops only on empty backlog / budget / stuck / guardrail.
- `checkpoint-task` — pause for approval after each task.
- `checkpoint-unit` — autonomous within a unit, pause at each independently-mergeable-cluster boundary.

Always-on guardrails (`reference/guardrails.md`):
- **Branch isolation** — dedicated loop branch; `main` protected.
- **Clean-worktree precondition** — refuse to start dirty (or auto-stash with flag).
- **Protected paths** — never edit `.env*`, secrets, CI credentials, lockfile-of-record without flag.
- **Command denylist** — block destructive shell (`rm -rf /`, history rewrite, `push --force`, package publish, `curl | sh`).
- **Permission allowlist** for headless — explicit `--allowedTools`; no blanket skip unless `--dangerously-skip-permissions` is explicitly passed.
- **Budget caps (auth-aware).** Enforced only at task boundaries (never mid-task — respects the §10 atomicity invariant); if the next task's projected cost would exceed remaining budget, halt cleanly *before* starting.
  - **API-key auth** → dollar cap: sum per-turn tokens from `stream-json` × a per-model price table in config (handles model tiering + new pricing); raw-token ceiling as fallback when a price is unknown.
  - **Subscription auth** → no dollars. Bound by max iterations / wallclock, and **rate-limit-aware backoff**: on a usage-limit / 429 response the loop checkpoints and either pauses until the window resets and auto-resumes, or halts with a clear "hit subscription limit — resume with X" message. It must never hammer a throttled endpoint.
  - Always also: max consecutive blocked tasks. Any breach → clean halt.
- **Stuck detection** — identical diff/error across retries, or gate never improving → abort task, don't burn budget.

**Unattended-mode reality (accepted risks, not mechanisms):**
- No human is present to answer permission prompts in `--detach`, so interactive gating can't fail-safe — it would just hang. The tool **allowlist + the prompt are the only intent guardrails**; therefore `--dangerously-skip-permissions` stays off by default and the allowlist stays tight.
- Prompt rules govern the model's *intent*, not *side effects of the repo's own tooling* (destructive test setup, a migration on the wrong env, a malicious dependency postinstall). This is a **known accepted risk** on trusted repos; the filesystem blast radius is bounded for free by running in an **isolated git worktree** (loop branch, `main` untouched).

---

## 10. State, resumption, observability

**State** — `.loop/state.json`: backlog with per-task status (`todo|in_progress|done|blocked`), retry counts, current index, commits, cumulative tokens/cost, timestamps. Checkpointed every iteration → kill-and-restart resumes cleanly (idempotent).

**Atomicity invariant — `clean worktree ⇔ between tasks`.** Every task is either atomically committed (done) or not-started; there is no partial state. On any mid-attempt halt (budget / `STOP` / crash), the harness discards the in-flight uncommitted changes (`git reset --hard`, or stash-with-label if you want to inspect) so the tree is always commit-aligned. Resume re-runs the interrupted task from scratch on a clean tree. This is what keeps the clean-worktree precondition (§9) and atomic commits from deadlocking each other.

**Logs** — `.loop/log/iteration-NNN.md` per attempt: task, filled prompt, action summary, gate output tail, commit sha, tokens/cost.

**Report** — `.loop/report.md` live dashboard: done/blocked/remaining counts, current task, spend vs budget, ETA, recent commits. Rendered on halt as the handoff summary.

**Notifications** — on halt (done / stuck / budget), optional desktop or push notification with the reason.

---

## 11. Execution & process lifecycle (Phase 6)

How the loop actually runs, and how you stop it.

- **Attached (default)** — the loop is bound to the launching session and ends when the session ends. Matches the intuition that closing the session stops the work. Right for supervised runs you're watching.
- **Detached (`--detach` / `--overnight`)** — OS-detached process (`Start-Process -WindowStyle Hidden` on Windows / `nohup … &` on unix) that **survives session/terminal close**. This is the *only* mode that keeps running after you leave, and the skill prints a **loud warning + the exact stop command** at launch so the decoupling is never a surprise.
- **Stop = `.loop/STOP` sentinel** — checked at every iteration boundary; present → clean, checkpointed halt (never mid-write). The `stop` command just creates the file. Cross-platform, no signal handling, no PID-hunting. The PID is still recorded in `state.json` as a hard-kill backstop, and an optional session-close hook can drop `STOP` automatically if you want "close = stop" even in detach mode.
- **Monitor** — `.loop/report.md` live dashboard; skill hands back a tail/watch command.
- **Resume** — relaunch reads `state.json` and continues from the last checkpoint (idempotent).
- **Single-instance lock** — `.loop/lock` (PID) prevents two loops racing the same repo/branch; a stale lock from a dead PID is auto-cleared.

## 12. Cross-platform

User is on Windows. Harness selection at recon time:
1. **`orchestrator.py`** if python3 present — preferred (robust JSON parsing, cost math, state).
2. **`loop.ps1`** on Windows without python.
3. **`loop.sh`** for bash/git-bash / macOS / Linux.

All three implement the same control flow and read the same `loop.config.json`, so behavior is identical regardless of runtime.

---

## 13. Config schema (`loop.config.json`, generated + user-overridable)

```jsonc
{
  "mode": "auto",                       // auto | checkpoint-task | checkpoint-unit
  "backlog": { "adapter": "markdown", "path": "BACKLOG.md" },
  "gate": ["pnpm install --frozen-lockfile", "pnpm lint", "pnpm typecheck", "pnpm test"],
  "models": {                           // per-task tiering; loop picks by complexity, escalates on retry
    "simple":       "claude-sonnet-5",
    "complex":      "claude-opus-4-8",  // medium/complex
    "very_complex": "claude-fable-5",   // priciest — only when tagged very-complex or explicitly requested
    "default":      "complex",          // used when triage is unavailable
    "escalate_on_retry": true           // sonnet-5 → opus-4-8 → fable-5
  },
  "git": { "branch": "loop/{ts}", "commit_per": "task", "pr_per": "unit", "pr_draft": true, "stack": false, "push": false },
  "budget": { "max_iterations": 50, "max_wallclock_min": 240,
              "max_retries": 3, "max_consecutive_blocked": 3,
              "max_cost_usd": 20,                 // API auth only; ignored on subscription
              "on_rate_limit": "pause-resume" },  // subscription: pause-resume | halt

  "guardrails": { "protected_paths": [".env*", "secrets/**"], "allowed_tools": ["Edit","Write","Bash","Read","Grep","Glob"] },
  "tdd": "logic-only",                  // logic-only | always | off
  "monorepo": { "scope_gate_to_touched_package": true }
}
```

---

## 14. Example run

```
$ /nocturne "add pagination to the users API and cover it with tests"

Phase 1  Detected: TypeScript · pnpm · vitest · eslint · tsc · GitHub Actions
Phase 2  Interactive decomposition → 6 tasks written to BACKLOG.md
Phase 3  Gate = pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test
Phase 4  Harness = orchestrator.py · branch loop/20260704 · commit per task
Phase 5  Plan preview:
           6 tasks · gate above · mode=auto · budget $20/240min · main protected
           Proceed? [GO / edit / cancel]
Phase 6  ▸ task 1/6 write failing test for page params … gate ✔ … commit a1b2c3
         ▸ task 2/6 implement pagination in handler … gate ✔ … commit d4e5f6
         …
Phase 7  Done: 6/6, 0 blocked · 9 commits · $6.40 · branch loop/20260704
         Open PR? push? (gh detected)
```

---

## 15. Resolved decisions

1. **Backlog sources (base):** `BACKLOG.md` (default) + GitHub issues + GitLab issues + interactive decomposition. Linear/Jira/Notion deferred — they slot in later via the plugin adapter interface, not built now.
2. **Model tiering (core):** per-task by complexity — sonnet-5 (simple) / opus-4-8 (medium-complex, default) / fable-5 (very complex only, priciest); triage when untagged; escalate a tier on gate failure. See §8.4.
3. **PR automation:** dependency-aware — one **draft** PR per **independently-mergeable unit** (§8.3), each branched off the default branch so no unit builds on unapproved sibling code; within-unit tasks stack. Never auto-merge; default branch stays protected. `--pr-per none` disables; `--pr-per task --stack` for the fully-dependent case.

Remaining to confirm: default cost cap (`$20`) and wallclock (`240 min`) — placeholders; adjust to taste.

---

## 16. Self-improvement (learned conventions) — fast-follow

The loop gets better *as it runs*: base prompt stays minimal, a small learned layer grows.

- **Rolling `.loop/learned.md`** — a bounded (~15 bullets), deduped list of repo-specific conventions the loop discovered (e.g. "use pnpm", "tests in `__tests__`", "lint needs `--max-warnings 0`"), injected into later iterations via `--append-system-prompt`. Bounded + additive-only, so it never bloats or rewrites the core prompt.
- **Populated from friction (≈free)** — the harness already sees gate failures/retries; the fix that turned red→green becomes a learned bullet so the loop never re-hits it.
- **Promote on finish** — durable learnings are proposed as a diff to the repo's real `CLAUDE.md` in the final report/PR, so the improvement outlives the run. Reviewed like any change.
- **Anti-degradation** — bounded size, dedupe, facts-not-rewrites; a learning that later correlates with failures is dropped. No prompt drift.

## 17. Future enhancements

- **External-tracker adapters** — Linear / Jira / Notion via the plugin interface + MCP.
- **Parallel loop** — independent units fanned out into git worktrees, each its own headless process, merged on green.
- **Self-grooming** — a periodic pass that re-orders/splits the backlog as the codebase changes.
