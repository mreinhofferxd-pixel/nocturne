---
name: loop-creator
description: Read a repo and its BACKLOG.md, then generate and launch a headless
  claude -p while-loop that autonomously works the backlog (implement -> verify ->
  commit) on a dedicated branch. v1 walking skeleton — markdown backlog, auto-detected
  quality gate, attached run, trust-but-verify harness, atomic commits, resumable.
  Use when the user wants to set up or start an autonomous dev loop over a backlog.
---

# loop-creator (v1)

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

Markdown backlog only · gate auto-detected from repo · attached run (no detach) ·
dedicated loop branch, no push/PR · single-instance lock + resumable state ·
simple caps (max_iterations, max_consecutive_failures, max_retries).

Out of v1: model tiering, PR automation, anti-gaming diff-guard, acceptance tests,
scope-drift flags, detach, budget-dollar nuance, github/gitlab adapters.

## Steps

### 1. Preflight
- Confirm target is a git repo and the worktree is clean (uncommitted BACKLOG.md
  is fine; anything else — ask the user to commit/stash first).
- Confirm `claude` CLI is on PATH and `python` runs (v1 requires python).
- Confirm a `BACKLOG.md` (or `TODO.md` / `PLAN.md`) with `- [ ]` checkboxes exists.
  If not, offer to help write one — a checkbox list of small, single-commit tasks.

### 2. Recon (light)
Detect the stack, package manager, and test/lint/typecheck tooling. Record a short
summary. This feeds the gate. (Full recon.json is a later increment.)

### 3. Gate synthesis
Follow `reference/gate-derivation.md`: CI config -> package scripts -> language
default. Produce an ordered command list. Prefer fast, deterministic commands.

### 4. Write the loop into the target repo
Create `.loop/` and drop in the harness:
- Copy `templates/orchestrator.py` -> `.loop/orchestrator.py`
- Copy `adapters/markdown_adapter.py` -> `.loop/markdown_adapter.py`
- Write `.loop/loop.config.json` (schema below).

The orchestrator writes `.loop/.gitignore` (`*`) itself so `.loop/` stays out of
git and out of `git clean`.

### 5. Preview & confirm (one-time human gate)
Show: backlog task count, the exact gate, the loop branch, and the caps. Require an
explicit GO before launching.

### 6. Launch (attached)
```
python .loop/orchestrator.py
```
Attached = tied to this session. The harness checks out `loop/<ts>`, works each
task, commits on green, checkpoints state every iteration.

- **Monitor:** `.loop/report.md` (live) and `.loop/log/iteration-*.md`.
- **Stop:** create `.loop/STOP` (honored at the next task boundary — never
  mid-write). PowerShell: `New-Item .loop/STOP`.
- **Resume:** re-run `python .loop/orchestrator.py`; it reads `.loop/state.json`
  and continues on the same branch.

### 7. Handoff
Summarize from `.loop/report.md`: done/blocked counts, commits, branch, halt reason.
Blocked tasks carry a reason. No push/PR in v1 — the user reviews the branch.

## loop.config.json (v1 schema)

```jsonc
{
  "mode": "auto",
  "backlog": { "adapter": "markdown", "path": "BACKLOG.md" },
  "gate": ["ruff check .", "pytest -q"],   // from gate-derivation
  "branch": "loop/{ts}",                    // {ts} filled at first launch, pinned in state
  "model": "claude-sonnet-5",               // Pro/subscription: sonnet+medium to conserve tokens; opus for hard tasks
  "effort": "medium",                       // claude --effort: low|medium|high|xhigh|max (omit to skip)
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
- Default model `claude-sonnet-5` + `effort: medium` suits Pro/subscription budgets; the
  harness passes `--effort` when set. Raise to opus / higher effort per run for hard work.
