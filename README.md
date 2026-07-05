# nocturne

![python](https://img.shields.io/badge/python-3.10+-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-323%20passing-brightgreen)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

nocturne is a Claude Code skill that turns a repo plus a spec/checkbox-backlog into a self-verifying autonomous dev loop: a design-layer Claude reads the repo, authors a tailored harness, and launches a headless `claude -p` while-loop that implements, verifies, and commits each task on a dedicated branch.

*a task exists in a done/not-done superposition until the harness observes it.*

## Why not just a loop?

"Define a loop and let it run" dies at the context window: one session working
a whole backlog drags every task's noise into the next, and quality decays as
the window fills. The actual fix is an outer loop that gives each task a fresh
session, carries state between sessions, and verifies results independently.
That is a real piece of engineering, not a prompt. nocturne is that outer loop: the
harness holds the backlog, budget, retries, and learnings; each task runs in a
clean headless `claude -p` session; nothing counts as done until the gate runs
green on a real commit.

## Install

One command. Installs the skill user-wide, so `/nocturne` works in every repo.

```bash
# macOS / Linux / WSL / Git Bash
curl -fsSL https://raw.githubusercontent.com/mreinhofferxd-pixel/nocturne/master/install.sh | bash
```

```powershell
# Windows / PowerShell 5.1+
irm https://raw.githubusercontent.com/mreinhofferxd-pixel/nocturne/master/install.ps1 | iex
```

A few seconds. Safe to re-run. Prefer a per-repo install? Copy
`.claude/skills/nocturne/` into the target repo's `.claude/skills/` instead.

## Quick start

You need the Claude Code CLI and `python` 3.10+ on PATH.

1. Open Claude Code in a git repo that has a `- [ ]` checkbox `BACKLOG.md` or a spec/design doc to groom.
2. Run `/nocturne`.

The skill previews the backlog, gate, branch, and caps, then waits for an explicit **GO** before launching.

The loop model runs with broad Bash access, so use it on repos you trust. Commits stay on a local loop branch; nothing is pushed.

## What it does

- **Auto-derived quality gate** - inferred from the repo, where an explicit `Done = <cmd>` statement outranks CI config, package scripts, and language defaults; the harness re-runs it independently.
- **Trust-but-verify** - done requires the gate green AND a real new commit AND a clean worktree; a self-report is never trusted.
- **Atomic commits** - one commit per task; failed attempts are fully discarded.
- **Rate-limit pause-resume** - a 429 never burns a retry; the loop sleeps to the reset and re-runs the same attempt.
- **Per-task model tiering** - with automatic retry escalation.
- **Anti-gaming diff guard** - rejects a green attempt that weakened a check or deleted an assertion instead of solving the task.
- **Acceptance criteria** - parsed from the backlog and enforced in the diff; non-codifiable ones are routed to a human checkpoint.
- **Budget guardrails** - dollar cap, wall-clock cap, per-task timeout, protected paths.
- **Observability** - a live in-terminal feed, a `.loop/report.md` dashboard, a global `~/.nocturne` run registry with statusline and events-feed surfaces, and a detached background mode.

## Configuration

The full `loop.config.json` schema lives in `.claude/skills/nocturne/SKILL.md`.
