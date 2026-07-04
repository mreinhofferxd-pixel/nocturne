---
name: nocturne
description: Read a repo and its BACKLOG.md (or groom a SPEC/design doc into one),
  then generate and launch a headless claude -p while-loop that autonomously works
  the backlog (implement -> verify -> commit) on a dedicated branch. v1 walking
  skeleton — markdown backlog or spec-groomed backlog, auto-detected quality gate,
  attached run, trust-but-verify harness, atomic commits, resumable. Use when the
  user wants to set up or start an autonomous dev loop over a backlog or a spec.
---

# nocturne (v1)

You (the design-layer Claude) inspect the target repo, author a tailored headless
loop, and launch it. A python harness (`orchestrator.py`) then drives a headless
`claude -p` process in a while-loop: pick task -> run claude -> **independently
re-run the gate + check git for a new commit** -> mark done/blocked -> repeat.

**Trust-but-verify:** the harness never trusts the model's self-report. Done
requires the gate green AND a real new commit AND a clean worktree.

**Atomicity invariant:** clean worktree <=> between tasks. Every task is either
atomically committed or fully discarded (`git reset --hard`). One commit per task.

Keep everything lean (strong models need structure, not hand-holding). The value
is the harness — gate, verify, state, atomic commits — not verbose prompt text.

## v1 scope

Markdown backlog, or groom a spec/design doc into one · gate auto-detected from repo · attached run (no detach) ·
dedicated loop branch, no push/PR · single-instance lock + resumable state ·
simple caps (max_iterations, max_consecutive_failures, max_retries).

Out of v1: model tiering, PR automation, anti-gaming diff-guard, acceptance tests,
scope-drift flags, detach, budget-dollar nuance, github/gitlab adapters.

## Steps

### 1. Preflight
- Confirm target is a git repo and the worktree is clean (uncommitted BACKLOG.md
  is fine; anything else — ask the user to commit/stash first).
- Confirm `claude` CLI is on PATH and `python` runs (v1 requires python).
- Confirm a **backlog source** exists — either a `BACKLOG.md` / `TODO.md` / `PLAN.md`
  with `- [ ]` checkboxes, or a spec/design doc (`SPEC.md`, `DESIGN.md`, a PRD) to
  groom from. If neither, offer to draft one interactively. The source is resolved
  in step 2.

### 2. Backlog acquisition (markdown or spec)
- **Checkbox backlog only** — use it as-is. It is the source of truth; skip to recon.
- **Spec/design doc only** — groom it into `BACKLOG.md` per
  `reference/spec-to-backlog.md`: an ordered, dependency-aware checkbox list of
  small, single-commit tasks, grouped into units by `##` headings. Diff the spec
  against the current repo so already-done work yields no task. Flag ambiguous items
  for the preview instead of guessing.
- **Both a checkbox backlog AND a spec** — default to the backlog as-is, but **offer a
  spec-sync / re-groom pass** (`reference/spec-to-backlog.md` "Spec-sync"): diff the
  spec against the *union* of (existing backlog tasks ∪ current repo state) and
  **append only the genuinely missing tasks** as new `- [ ]` items under the right
  `##` units — never rewrite, reorder, or re-check existing lines. Preview the
  new-task count + any flagged items; require GO. Idempotent: if nothing is missing
  (all spec work is already listed or already built) it appends nothing. This is the
  manual reconcile step toward self-grooming (spec §17); the human GO stays.
- Once resolved the run **converges to the markdown adapter** — the harness only ever
  reads checkboxes, never the spec. The result is one `BACKLOG.md` the adapter drives.

### 3. Recon (light)
Detect the stack, package manager, and test/lint/typecheck tooling. Record a short
summary. This feeds the gate. (Full recon.json is a later increment.)

### 4. Gate synthesis
Follow `reference/gate-derivation.md`: CI config -> package scripts -> language
default. Produce an ordered command list. Prefer fast, deterministic commands.

### 5. Write the loop into the target repo
Create `.loop/` and drop in the harness:
- Copy `templates/orchestrator.py` -> `.loop/orchestrator.py`
- Copy `adapters/markdown_adapter.py` -> `.loop/markdown_adapter.py`
- Write `.loop/loop.config.json` (schema below).

The orchestrator writes `.loop/.gitignore` (`*`) itself so `.loop/` stays out of
git and out of `git clean`.

### 6. Preview & confirm (one-time human gate)
Show: backlog task count, the exact gate, the loop branch, and the caps. If the
backlog was groomed from a spec, also show the unit count and any **flagged/ambiguous**
items for the user to resolve. Require an explicit GO before launching.

### 7. Launch (attached)
```
python .loop/orchestrator.py
```
Attached = tied to this session. The harness checks out `loop/<ts>`, works each
task, commits on green, checkpoints state every iteration.

- **Monitor (in-session):** the run is attached, so the harness **streams the decoded
  feed straight to this terminal** — tool calls, assistant text, per-turn cost — and you
  watch it live in-context. No separate viewer or manual tail needed. Toggle with
  `observability.live_feed` (default true).
  - `.loop/activity.log` — the same feed mirrored to a file (post-hoc review or a second
    pane): `Get-Content .loop/activity.log -Wait` (PowerShell) / `tail -f .loop/activity.log`.
  - `.loop/report.md` — task-boundary dashboard (done/blocked/todo, cost).
  - `.loop/log/iteration-*.md` — raw stream-json per attempt, also written live.
- **Stop:** create `.loop/STOP` (honored at the next task boundary — never
  mid-write). PowerShell: `New-Item .loop/STOP`.
- **Resume:** re-run `python .loop/orchestrator.py`; it reads `.loop/state.json`
  and continues on the same branch.

### 8. Handoff
Summarize from `.loop/report.md`: done/blocked counts, commits, branch, halt reason.
Blocked tasks carry a reason. No push/PR in v1 — the user reviews the branch.

## loop.config.json (v1 schema)

```jsonc
{
  "mode": "auto",
  "backlog": { "adapter": "markdown", "path": "BACKLOG.md" },
  "gate": ["ruff check .", "pytest -q"],   // from gate-derivation
  "branch": "loop/{ts}",                    // {ts} filled at first launch, pinned in state
  "model": "claude-opus-4-8",               // default opus+xhigh for max quality; drop to sonnet-5+medium to conserve tokens
  "effort": "xhigh",                        // claude --effort: low|medium|high|xhigh|max (omit to skip)
  "on_rate_limit": "pause-resume",          // §9: pause-resume (sleep to reset, re-run same attempt) | halt (stop w/ resume msg)
  "max_rate_limit_wait_s": 21600,           // cap on a single pause (6h); a longer reset halts instead of sleeping
  "oversize_file_threshold": 25,            // §8.7: a blocked task whose last diff touches more files than this is flagged "too large — split needed"
  "observability": { "live_feed": true },   // stream the decoded feed to this terminal (in-session live view); false = silent unattended
  "budget": {
    "max_iterations": 50,
    "max_consecutive_failures": 3,
    "max_retries": 3,
    "max_turns": 30,
    "max_seconds_per_task": 1800
  },
  "guardrails": { "allowed_tools": ["Edit", "Write", "Bash", "Read", "Grep", "Glob"] }
}
```

## How the harness treats the backlog

- `- [ ]` = todo, `- [x]` = done. `next_task` = first unchecked.
- On done: the harness checks the box and **folds that edit into the task's commit**
  (`git commit --amend`) so one commit == one done task and the tree stays clean.
- Blocked tasks are tracked in `.loop/state.json` (not written into BACKLOG.md, so
  the worktree never goes dirty between tasks) and are skipped on later passes.

## Notes / accepted risks (v1)

- `--allowedTools` includes `Bash` broadly so the model can run the gate and commit.
  On a trusted repo this is the accepted risk (no denylist in v1).
- Attached only: closing the session ends the loop. Detached/overnight is fast-follow.
- Default model `claude-opus-4-8` + `effort: xhigh` for maximum quality; the harness passes
  `--effort` when set. Drop to `claude-sonnet-5` + `medium` per run to conserve tokens on a budget.
- Rate limits (§9): a 429 / usage-limit rejection is **not** a task failure — it never
  burns a retry or bumps `consecutive_failures`. Default `on_rate_limit: pause-resume`
  discards in-flight work (atomicity), sleeps until `resetsAt` (+small buffer), then
  re-runs the same attempt; progress streams to `.loop/activity.log` + a `PAUSED` banner
  in `report.md`. Set `halt` to stop cleanly with a resume command instead.
  `max_rate_limit_wait_s` (default 6h, covers a five-hour reset) caps one pause — a
  longer reset halts rather than sleeps. Built by hand, never dogfooded (a mid-build 429
  would corrupt the run testing it).
