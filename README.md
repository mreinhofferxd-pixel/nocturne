# nocturne

![python](https://img.shields.io/badge/python-3.10+-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-323%20passing-brightgreen)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

nocturne is a Claude Code skill that turns a repo plus a checkbox backlog into a self-verifying autonomous dev loop — a design-layer Claude reads the repo, authors a tailored harness, and launches a headless `claude -p` while-loop that implements, verifies, and commits each task on a dedicated branch.

*a task exists in a done/not-done superposition until the harness observes it.*

## Quick start

Nothing to install. You need:

- the Claude Code CLI
- `python` 3.10+ on PATH
- a git repo with either a `- [ ]` checkbox `BACKLOG.md` or a spec/design doc to groom

Then:

1. Copy `.claude/skills/nocturne/` into the target repo's `.claude/skills/`.
2. Open Claude Code there and run `/nocturne`.

The skill previews the backlog, gate, branch, and caps, then waits for an explicit **GO** before launching.

The loop model runs with broad Bash access — use it on repos you trust. Commits stay on a local loop branch; nothing is pushed.

## What it does

- **Auto-derived quality gate** — inferred from the repo, where an explicit `Done = <cmd>` statement outranks CI config, package scripts, and language defaults; the harness re-runs it independently.
- **Trust-but-verify** — done requires the gate green AND a real new commit AND a clean worktree; a self-report is never trusted.
- **Atomic commits** — one commit per task; failed attempts are fully discarded.
- **Rate-limit pause-resume** — a 429 never burns a retry; the loop sleeps to the reset and re-runs the same attempt.
- **Per-task model tiering** — with automatic retry escalation.
- **Anti-gaming diff guard** — rejects a green attempt that weakened a check or deleted an assertion instead of solving the task.
- **Acceptance criteria** — parsed from the backlog and enforced in the diff; non-codifiable ones are routed to a human checkpoint.
- **Budget guardrails** — dollar cap, wall-clock cap, per-task timeout, protected paths.
- **Observability** — a live in-terminal feed, a `.loop/report.md` dashboard, a global `~/.nocturne` run registry with statusline and events-feed surfaces, and a detached background mode.

## Configuration

The full `loop.config.json` schema lives in `.claude/skills/nocturne/SKILL.md`.
