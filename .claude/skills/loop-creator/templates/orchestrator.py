#!/usr/bin/env python3
"""loop-creator v1 orchestrator (walking skeleton).

The harness owns control flow. TRUST-BUT-VERIFY: after each attempt the harness
independently re-runs the gate AND checks git for a new commit. The model's
self-report is never trusted.

ATOMICITY INVARIANT: clean worktree <=> between tasks. Every task ends either
atomically committed (done) or fully discarded (git reset --hard). One commit
per completed task (the backlog checkbox is folded into it via --amend).

v1 scope: markdown adapter, attached run, single-instance lock, resumable state,
dedicated loop branch, no push/PR. Simple caps: max_iterations,
max_consecutive_failures, max_retries.

Run:   python .loop/orchestrator.py
Stop:  create .loop/STOP  (honored at the next task boundary)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("LOOP_REPO", ".")).resolve()
LOOP = ROOT / ".loop"
CONFIG = LOOP / "loop.config.json"
STATE = LOOP / "state.json"
LOCK = LOOP / "lock"
STOP = LOOP / "STOP"
LOGDIR = LOOP / "log"
REPORT = LOOP / "report.md"

sys.path.insert(0, str(LOOP))  # markdown_adapter.py is copied alongside this file
from markdown_adapter import MarkdownBacklog  # noqa: E402

IS_WIN = os.name == "nt"


# ---------------------------------------------------------------- shell / git
def run(cmd, shell=False, input_text=None, timeout=None):
    # Force UTF-8 decoding: claude's stream-json is UTF-8, and the Windows OEM/ANSI
    # locale (e.g. cp1252) crashes on bytes it can't map. errors="replace" keeps a
    # stray byte from ever killing the harness.
    return subprocess.run(
        cmd, cwd=str(ROOT), shell=shell, input=input_text,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


def git(*args, check=True):
    r = run(["git", *args])
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def head_sha():
    return git("rev-parse", "HEAD")


def is_git_repo():
    return run(["git", "rev-parse", "--is-inside-work-tree"]).returncode == 0


def working_dirty(exclude):
    """True if any tracked/untracked path (outside `exclude`) is dirty.
    .loop/ is gitignored so it never appears here."""
    out = git("status", "--porcelain")
    if not out:
        return False
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if path in exclude:
            continue
        return True
    return False


def discard_inflight(before, backlog):
    """Restore atomicity: drop the model's commit (if any) and all changes,
    keeping the untracked backlog and .loop/ intact."""
    git("reset", "--hard", before)
    git("clean", "-fd", "-e", backlog, "-e", ".loop")


# ---------------------------------------------------------------- lock / pid
def pid_alive(pid):
    if IS_WIN:
        r = run(["tasklist", "/nh", "/fi", f"pid eq {pid}"])
        return str(pid) in (r.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return isinstance(sys.exc_info()[1], PermissionError)
    except OSError:
        return False


def acquire_lock():
    if LOCK.exists():
        try:
            old = int(LOCK.read_text().strip())
        except ValueError:
            old = None
        if old and pid_alive(old):
            print(f"[loop] another instance is running (pid {old}). abort.")
            sys.exit(1)
        print(f"[loop] clearing stale lock (pid {old}).")
    LOCK.write_text(str(os.getpid()))


def release_lock():
    try:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- state
def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return None


def save_state(state):
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- branch
def resolve_branch(pattern):
    return pattern.replace("{ts}", time.strftime("%Y%m%d-%H%M%S"))


def ensure_branch(branch):
    if git("branch", "--list", branch).strip():
        git("checkout", branch)
    else:
        git("checkout", "-b", branch)


# ---------------------------------------------------------------- gate
def run_gate(gate_cmds):
    """Harness re-runs the gate independently. Returns (ok, tail_output)."""
    if not gate_cmds:
        return True, "(no gate configured)"
    buf = []
    for cmd in gate_cmds:
        r = run(cmd, shell=True, timeout=3600)
        buf.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
        if r.returncode != 0:
            tail = "\n".join(buf)[-4000:]
            return False, tail
    return True, "\n".join(buf)[-2000:]


# ---------------------------------------------------------------- claude
def build_prompt(task, gate, prior):
    gate_str = " && ".join(gate) if gate else "(none configured)"
    p = (
        f"Task: {task.title}\n\n"
        f"Make the quality gate pass, then commit your work.\n\n"
        f"Quality gate (must pass): {gate_str}\n\n"
        f"Rules:\n"
        f"- Stay within the scope of this one task.\n"
        f"- Do not weaken tests, gate config, lint, or CI to make the gate pass.\n"
        f"- Finish with exactly one commit (conventional-commit message). Do not push.\n"
        f"- Do not edit BACKLOG.md or anything under .loop/."
    )
    if prior:
        p += f"\n\nYour previous attempt failed the gate:\n{prior}\n\nDiagnose and fix."
    return p


def run_claude(prompt, cfg, logfile):
    tools = ",".join(cfg["guardrails"]["allowed_tools"])
    budget = cfg.get("budget", {})
    cmd = (
        f'claude -p --output-format stream-json --verbose '
        f'--permission-mode acceptEdits '
        f'--allowedTools "{tools}" '
        f'--max-turns {budget.get("max_turns", 30)} '
        f'--model {cfg["model"]}'
    )
    if cfg.get("effort"):
        cmd += f' --effort {cfg["effort"]}'
    stdout = ""
    try:
        r = run(cmd, shell=True, input_text=prompt,
                timeout=budget.get("max_seconds_per_task", 1800))
        stdout = r.stdout or ""
        out = stdout + (r.stderr or "")
    except subprocess.TimeoutExpired:
        out = "[loop] claude timed out."
    logfile.write_text(out, encoding="utf-8")
    return parse_cost(stdout)


def parse_cost(stdout):
    """Best-effort: pull total_cost_usd from the final stream-json result event."""
    cost = 0.0
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result" and "total_cost_usd" in ev:
            cost = ev["total_cost_usd"]
    return cost


# ---------------------------------------------------------------- report
def write_report(state, tasks, halt=None):
    done = sum(1 for t in tasks if t.done)
    blocked = [tid for tid, r in state["results"].items() if r.get("status") == "blocked"]
    todo = sum(1 for t in tasks if not t.done and t.id not in blocked)
    lines = [
        "# loop-creator report",
        "",
        f"- branch: `{state['branch']}`",
        f"- iterations: {state['iterations']}",
        f"- done: {done}   blocked: {len(blocked)}   todo: {todo}",
        f"- consecutive failures: {state['consecutive_failures']}",
        f"- cumulative cost (usd, best-effort): {state.get('cost_usd', 0):.4f}",
        f"- updated: {state.get('updated_at', '')}",
    ]
    if halt:
        lines += ["", f"**HALTED: {halt}**"]
    lines += ["", "## tasks"]
    for t in tasks:
        res = state["results"].get(t.id, {})
        status = "done" if t.done else res.get("status", "todo")
        note = f" — {res.get('reason', '')}" if status == "blocked" else ""
        sha = f" ({res['commit'][:9]})" if res.get("commit") else ""
        lines.append(f"- [{('x' if t.done else ' ')}] {t.title} · {status}{sha}{note}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- selection
def pick_task(adapter, state):
    blocked = {tid for tid, r in state["results"].items() if r.get("status") == "blocked"}
    for t in adapter.list():
        if not t.done and t.id not in blocked:
            return t
    return None


# ---------------------------------------------------------------- main loop
def process_task(task, cfg, adapter, state, backlog_rel):
    """Run one task through up to max_retries attempts. Returns (done, sha, reason)."""
    gate = cfg["gate"]
    max_retries = cfg.get("budget", {}).get("max_retries", 3)
    before = head_sha()
    prior = None

    for attempt in range(1, max_retries + 1):
        n = state["iterations"] + 1
        logfile = LOGDIR / f"iteration-{n:03d}-a{attempt}.md"
        print(f"[loop] task {task.id} '{task.title}' attempt {attempt}/{max_retries}")

        prompt = build_prompt(task, gate, prior)
        cost = run_claude(prompt, cfg, logfile)
        state["cost_usd"] = state.get("cost_usd", 0.0) + cost

        new_commit = head_sha() != before
        dirty = working_dirty({backlog_rel})

        if not new_commit:
            prior = "No commit was produced. You must commit your work."
            discard_inflight(before, backlog_rel)
            continue
        if dirty:
            prior = "Uncommitted changes remained after your commit. Commit everything in one commit."
            discard_inflight(before, backlog_rel)
            continue

        ok, gate_out = run_gate(gate)
        if ok:
            adapter.mark_done(task)                 # check the box in BACKLOG.md
            git("add", backlog_rel)
            git("commit", "--amend", "--no-edit")   # fold checkbox into the task commit
            return True, head_sha(), None

        prior = gate_out
        discard_inflight(before, backlog_rel)

    return False, None, (prior or "gate never passed")[:500]


def main():
    if not LOOP.exists():
        print(f"[loop] no .loop/ at {ROOT}. run the loop-creator skill first.")
        sys.exit(1)
    if not CONFIG.exists():
        print(f"[loop] missing {CONFIG}.")
        sys.exit(1)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    LOGDIR.mkdir(parents=True, exist_ok=True)

    # --- preflight
    if not is_git_repo():
        print("[loop] not a git repository. abort.")
        sys.exit(1)
    if run(["git", "--version"]).returncode != 0:
        print("[loop] git not available. abort.")
        sys.exit(1)

    backlog_rel = cfg["backlog"]["path"]
    adapter = MarkdownBacklog(str(ROOT / backlog_rel))

    # keep .loop out of git so reset/clean and clean-worktree checks ignore it
    gi = LOOP / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")

    if working_dirty({backlog_rel}):
        print("[loop] worktree is dirty (commit or stash first). abort.")
        sys.exit(1)

    acquire_lock()
    halt = "unknown"
    try:
        # --- state + branch
        state = load_state()
        if state is None:
            state = {
                "branch": resolve_branch(cfg.get("branch", "loop/{ts}")),
                "iterations": 0,
                "consecutive_failures": 0,
                "cost_usd": 0.0,
                "results": {},
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        state["pid"] = os.getpid()
        ensure_branch(state["branch"])
        save_state(state)

        max_iter = cfg.get("budget", {}).get("max_iterations", 50)
        max_consec = cfg.get("budget", {}).get("max_consecutive_failures", 3)

        while True:
            if STOP.exists():
                STOP.unlink()
                halt = "STOP sentinel"
                break
            if state["iterations"] >= max_iter:
                halt = "max_iterations reached"
                break
            if state["consecutive_failures"] >= max_consec:
                halt = "max_consecutive_failures reached"
                break

            task = pick_task(adapter, state)
            if task is None:
                halt = "backlog empty"
                break

            done, sha, reason = process_task(task, cfg, adapter, state, backlog_rel)
            if done:
                state["results"][task.id] = {"status": "done", "commit": sha,
                                             "title": task.title}
                state["consecutive_failures"] = 0
                print(f"[loop] DONE {task.id} -> {sha[:9]}")
            else:
                discard_inflight(head_sha(), backlog_rel)  # belt + braces: ensure clean
                prev = state["results"].get(task.id, {})
                state["results"][task.id] = {
                    "status": "blocked", "reason": reason, "title": task.title,
                    "retries": prev.get("retries", 0) + 1,
                }
                state["consecutive_failures"] += 1
                print(f"[loop] BLOCKED {task.id}: {reason}")

            state["iterations"] += 1
            save_state(state)
            write_report(state, adapter.list())

        save_state(state)
        write_report(state, adapter.list(), halt=halt)
        print(f"[loop] halt: {halt}")
        print(f"[loop] report: {REPORT}")
    finally:
        # discard any in-flight work so the tree is always commit-aligned
        try:
            if is_git_repo():
                git("reset", "--hard", check=False)
                git("clean", "-fd", "-e", cfg["backlog"]["path"], "-e", ".loop", check=False)
        except Exception:
            pass
        release_lock()


if __name__ == "__main__":
    main()
