#!/usr/bin/env python3
"""nocturne v1 orchestrator (walking skeleton).

The harness owns control flow. TRUST-BUT-VERIFY: after each attempt the harness
independently re-runs the gate AND checks git for a new commit. The model's
self-report is never trusted.

ATOMICITY INVARIANT: clean worktree <=> between tasks. Every task ends either
atomically committed (done) or fully discarded (git reset --hard). One commit
per completed task (the backlog checkbox is folded into it via --amend).

v1 scope: markdown adapter, attached run, single-instance lock, resumable state,
dedicated loop branch, no push/PR. Simple caps: max_iterations,
max_consecutive_failures, max_retries.

Run:    python .loop/orchestrator.py
Stop:   python .loop/orchestrator.py stop    (drops .loop/STOP; halts at boundary)
Status: python .loop/orchestrator.py status  (prints .loop/report.md)
"""
import collections
import fnmatch
import json
import os
import re
import subprocess
import sys
import threading
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
ACTIVITY = LOOP / "activity.log"   # decoded, tail-able live feed of the running session
LIVE_FEED = True   # also stream the decoded feed to stdout (in-session live view); set from config in main()
LEARNED = LOOP / "learned.md"      # §16 rolling repo conventions, injected each iteration

sys.path.insert(0, str(LOOP))  # markdown_adapter.py is copied alongside this file
from markdown_adapter import MarkdownBacklog  # noqa: E402

IS_WIN = os.name == "nt"

# Harden our OWN stdout/stderr, not just subprocess decoding (see run()). Windows
# consoles default to a non-UTF-8 code page (cp1252) that raises UnicodeEncodeError
# on characters common in backlog task titles and gate output (arrows, em-dashes,
# section signs). errors="replace" keeps a stray glyph from ever killing the loop.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------- model tiering
# Per-task model selection by complexity (spec §8.4). Cheap-first: pick the
# cheapest tier a task's tag allows, then climb one tier per gate-failure retry
# (sonnet-5 -> opus-4-8 -> fable-5). Only an explicit very-complex tag reaches
# the priciest tier.
DEFAULT_MODEL = "claude-opus-4-8"
TIER_MODELS = {
    "simple": "claude-sonnet-5",
    "complex": DEFAULT_MODEL,
    "very-complex": "claude-fable-5",
}
ESCALATION_LADDER = ["claude-sonnet-5", "claude-opus-4-8", "claude-fable-5"]
_TIER_TAG = re.compile(r"\s*\[(very-complex|complex|simple)\]\s*$", re.IGNORECASE)


def parse_tier(title):
    """Extract an optional trailing [simple|complex|very-complex] complexity tag
    from a task title. Returns the lowercased tier, or None when untagged."""
    m = _TIER_TAG.search(title or "")
    return m.group(1).lower() if m else None


def pick_model(task, config):
    """Choose a task's model by complexity tier (spec §8.4). A tier tag on the
    title maps to its tier model; an untagged task falls to the config default.
    Config's `tier_models` overrides individual tiers."""
    tier_models = {**TIER_MODELS, **config.get("tier_models", {})}
    default = config.get("model", DEFAULT_MODEL)
    tier = parse_tier(task.title)
    if tier and tier in tier_models:
        return tier_models[tier]
    return default


def escalate(model, config):
    """Bump one tier up the escalation ladder on a gate-failure retry (spec §8.4:
    sonnet-5 -> opus-4-8 -> fable-5). Returns the model unchanged when already at
    the top tier or not on the ladder."""
    ladder = config.get("escalation_ladder", ESCALATION_LADDER)
    if model not in ladder:
        return model
    return ladder[min(ladder.index(model) + 1, len(ladder) - 1)]


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


def _porcelain_paths(porcelain_text):
    """Yield the path from each `git status --porcelain` line. Porcelain encodes
    status in columns 0-1 and the path from column 3, so this MUST run on RAW
    output -- stripping the leading space of a " M file" line (as the git() helper
    does) shifts the offset and misparses the name. Pure, so the offset logic is
    unit-testable without a repo."""
    for line in (porcelain_text or "").splitlines():
        if not line.strip():
            continue
        yield line[3:].strip().strip('"')


def working_dirty(exclude):
    """True if any tracked/untracked path (outside `exclude`) is dirty.
    .loop/ is gitignored so it never appears here. Reads RAW stdout (not the
    stripped git() helper) so porcelain's leading status columns stay intact --
    otherwise a modified-but-excluded backlog (" M BACKLOG.md") misparses and the
    preflight falsely reports the tree dirty."""
    out = run(["git", "status", "--porcelain"]).stdout
    return any(p not in exclude for p in _porcelain_paths(out))


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


def baseline_halt_reason(ok, tail, require_green):
    """Halt message when the pre-run baseline gate is RED, else None (dogfood #6).

    The loop assumes a green baseline: a pre-existing gate failure would surface
    inside the FIRST task's attempts and be mislabeled a task failure (falsely
    blocked -- symphony's red ruff baseline). When `require_green` is true and the
    baseline run failed, return an actionable halt naming the situation, the fix
    (repair the repo or adjust the gate; `require_green_baseline: false` opts
    out), and a short excerpt of the failing tail. Pure, so the decision is
    unit-testable without running a gate."""
    if not require_green or ok:
        return None
    excerpt = (tail or "").strip()
    if len(excerpt) > 400:
        excerpt = "..." + excerpt[-400:]
    return (
        "baseline gate is RED before any task ran -- fix the repo or adjust the "
        "gate (or set `require_green_baseline: false` to run anyway). "
        f"Gate tail: {excerpt}"
    )


# ---------------------------------------------------------------- claude
def build_prompt(task, gate, prior, flags=None):
    gate_str = " && ".join(gate) if gate else "(none configured)"
    p = (
        f"Task: {task.title}\n\n"
        f"Make the quality gate pass, then commit your work.\n\n"
        f"Quality gate (must pass): {gate_str}\n\n"
        f"Rules:\n"
        f"- Stay within the scope of this one task.\n"
        f"- Do not weaken tests, gate config, lint, or CI to make the gate pass.\n"
        f"- Finish with exactly one commit (conventional-commit message). Do not push.\n"
        f"- Do not edit BACKLOG.md or anything under .loop/.\n"
        f"- If your work invalidates a LATER backlog task's premise (e.g. a changed "
        f"model or API shape), add one line to your commit body: "
        f"'LOOP-FLAG: <what changed>'."
    )
    acceptance = getattr(task, "acceptance", None)
    if acceptance:
        p += (
            "\n- Hard rule: the finished work must satisfy this acceptance "
            f"criterion: {acceptance}. A test pinning this criterion must be "
            "present."
        )
    p += format_flag_notice(flags)
    if prior:
        p += f"\n\nYour previous attempt failed the gate:\n{prior}\n\nDiagnose and fix."
    return p


def run_claude(prompt, cfg, logfile, model=None, label=""):
    tools = ",".join(cfg["guardrails"]["allowed_tools"])
    budget = cfg.get("budget", {})
    model = model or cfg["model"]
    cmd = (
        f'claude -p --output-format stream-json --verbose '
        f'--permission-mode acceptEdits '
        f'--allowedTools "{tools}" '
        f'--max-turns {budget.get("max_turns", 30)} '
        f'--model {model}'
    )
    if cfg.get("effort"):
        cmd += f' --effort {cfg["effort"]}'
    cmd += _learned_flag(LEARNED)   # §16: inject rolling learned conventions when present
    timeout = budget.get("max_seconds_per_task", 1800)

    # Stream stdout line-by-line so the raw log is tail-able live and activity.log
    # gets a decoded, readable running feed. Full stdout is still captured for the
    # cost parse. A watchdog thread enforces the per-task timeout even if the child
    # hangs producing no output (a plain readline loop would otherwise block).
    if label:
        _append_activity(f"\n── {label} ──")
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), shell=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    chunks = []
    try:
        if proc.stdin:
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        with logfile.open("w", encoding="utf-8") as lf:
            for line in proc.stdout:
                chunks.append(line)
                lf.write(line)
                lf.flush()
                emit_activity(line)
        proc.wait()
    finally:
        timer.cancel()
    stdout = "".join(chunks)
    if not stdout:
        stdout = "[loop] claude produced no output (killed or timed out)."
        logfile.write_text(stdout, encoding="utf-8")
    events = parse_events(stdout)
    return ClaudeResult(
        cost=parse_cost(events),
        rate_limited=is_rate_limited(events),
        resets_at=rate_limit_reset(events),
    )


def parse_events(stdout):
    """Parse stream-json stdout into a list of event dicts (non-JSON lines skipped).
    Walked once per attempt, then shared by parse_cost / is_rate_limited /
    rate_limit_reset."""
    events = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def parse_cost(events):
    """Best-effort: pull total_cost_usd from the final stream-json result event."""
    cost = 0.0
    for ev in events:
        if ev.get("type") == "result" and "total_cost_usd" in ev:
            cost = ev["total_cost_usd"]
    return cost


# ---------------------------------------------------------------- activity feed
def _append_activity(text):
    try:
        with ACTIVITY.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def feed_lines(ev, stamp):
    """Pure: stamped, human-readable feed lines for one stream-json event.
    Shared by the activity.log writer and the in-session live stdout feed."""
    return [f"{stamp} {msg}" for msg in _activity_line(ev)]


def emit_activity(line):
    """Decode one stream-json line -> append to activity.log AND, when LIVE_FEED is
    on, stream it to stdout so the attached session shows the run live in-context."""
    line = line.strip()
    if not line.startswith("{"):
        return
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return
    stamp = time.strftime("%H:%M:%S")
    for msg in feed_lines(ev, stamp):
        _append_activity(msg)
        if LIVE_FEED:
            print("  " + msg, flush=True)


def task_banner(task, attempt, max_retries, model, cost):
    """Pure: one-line session header for a task attempt (model + running cost)."""
    return (f"▶ {task.id} '{task.title}' · attempt {attempt}/{max_retries} · "
            f"{model} · ${cost:.2f}")


def _tool_summary(name, inp):
    """One-line summary of a tool_use input (command / path / pattern)."""
    if not isinstance(inp, dict):
        return name
    for key in ("command", "file_path", "pattern", "path", "url"):
        if key in inp:
            val = " ".join(str(inp[key]).split())
            return f"{name}: {val[:100]}"
    return name


def _activity_line(ev):
    """Pure: map a stream-json event to zero or more human-readable feed lines."""
    t = ev.get("type")
    if t == "system" and ev.get("subtype") == "init":
        return [f"▶ session start · model={ev.get('model', '?')}"]
    if t == "rate_limit_event":
        info = ev.get("rate_limit_info", {})
        if info.get("status") == "rejected":
            return [f"⏳ RATE LIMITED ({info.get('rateLimitType', '?')})"]
        return []
    if t == "assistant":
        out = []
        for block in ev.get("message", {}).get("content", []):
            bt = block.get("type")
            if bt == "text":
                txt = " ".join(block.get("text", "").split())
                if txt:
                    out.append("💬 " + txt[:140])
            elif bt == "tool_use":
                out.append("🔧 " + _tool_summary(block.get("name", "?"), block.get("input", {})))
        return out
    if t == "result":
        mark = "✖" if ev.get("is_error") else "■"
        cost = ev.get("total_cost_usd", 0) or 0
        return [f"{mark} result: {ev.get('subtype', '?')} · turns={ev.get('num_turns', '?')} · ${cost:.4f}"]
    return []


# ---------------------------------------------------------------- report
def write_report(state, tasks, halt=None, note=None):
    done = sum(1 for t in tasks if t.done)
    blocked = [tid for tid, r in state["results"].items() if r.get("status") == "blocked"]
    todo = sum(1 for t in tasks if not t.done and t.id not in blocked)
    lines = [
        "# nocturne report",
        "",
        f"- branch: `{state['branch']}`",
        f"- iterations: {state['iterations']}",
        f"- done: {done}   blocked: {len(blocked)}   todo: {todo}",
        f"- consecutive failures: {state['consecutive_failures']}",
        f"- cumulative cost (usd, best-effort): {state.get('cost_usd', 0):.4f}",
        f"- updated: {state.get('updated_at', '')}",
    ]
    if note:
        lines += ["", f"**PAUSED: {note}**"]
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


# ---------------------------------------------------------------- checkpoint modes
# Spec section 9: `mode` controls whether the loop pauses at task boundaries instead
# of working the whole backlog unattended. "auto" (default) never pauses;
# "checkpoint-task" pauses after every completed task; "checkpoint-unit" pauses only
# at a unit boundary -- the next task belongs to a different ## heading group (8.3). A
# pause is checked ONLY after a DONE task (never a blocked one), so the halt is clean +
# resumable: the next run picks up at the next todo. Pure decision, unit-testable.
def should_checkpoint(mode, current_task, next_task):
    """True when the loop should pause after `current_task` completes (spec section 9).
    False for mode "auto" or when there is no next task (nothing left to pause
    before). "checkpoint-task" always pauses; "checkpoint-unit" pauses only when the
    next task's unit differs from the current task's (a 8.3 unit boundary). An
    unknown mode never pauses (degrades to auto). Pure."""
    if mode == "auto" or next_task is None:
        return False
    if mode == "checkpoint-task":
        return True
    if mode == "checkpoint-unit":
        return getattr(next_task, "unit", "") != getattr(current_task, "unit", "")
    return False


# ---------------------------------------------------------------- stuck check
def no_progress(prev_diff, cur_diff):
    """True when an attempt reproduced the previous attempt's diff verbatim.

    Pure helper (spec §8.1). Identical diffs across retries mean the model is
    spinning without converging, so the harness breaks early instead of burning
    the remaining budget. The first attempt (prev_diff is None) can never be
    stuck; two empty diffs in a row count as stuck (model did nothing twice)."""
    return prev_diff is not None and prev_diff == cur_diff


# ---------------------------------------------------------------- diff-guard (anti-gaming)
# Spec 8.5: "green" alone is never enough. The cheapest way to pass a gate is to
# weaken it -- add a skip/ignore/disable marker, or delete an assertion -- instead
# of solving the task. is_suppressing_diff classifies an attempt's diff; the
# harness rejects an otherwise-green attempt whose diff suppresses coverage,
# unless the task opts in with a [modifies-tests]/[refactor-tests] tag (guard
# relaxed for that task only).

# Tokens that, when ADDED, silence a check rather than satisfy it.
_SUPPRESSION_MARKER = re.compile(
    r"""
      \#\s*type:\s*ignore          # python: mypy blanket ignore
    | \#\s*noqa                    # python: flake8/ruff line suppression
    | @ts-ignore | @ts-nocheck     # typescript: silence line / whole file
    | eslint-disable               # js: disable rule(s) (incl. -next-line/-line)
    | \bxfail\b                    # pytest: expected-fail marker
    | \bxit\b | \bxdescribe\b      # jasmine/jest/mocha: pending spec
    | mark\.skip                   # pytest: @pytest.mark.skip[if]
    | \.skip\s*[\(\.]              # jest/mocha/pytest: it.skip( / describe.skip.
    | \bskip\s*\(                  # pytest.skip( / unittest skip(
    | \bskip(?:if|unless)?\b       # bare skip / skipif / skipunless marker
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Lines that ASSERT something. A net removal shrinks what the suite checks.
_ASSERTION = re.compile(
    r"""
      \bassert\b                   # python assert / node assert(
    | \bexpect\s*\(                # jest/chai expect(
    | self\.assert\w*\s*\(         # unittest assertEqual/assertTrue/...
    | \.should\b                   # chai should
    | pytest\.raises               # pytest context-manager assertion
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TESTS_TAG = re.compile(r"\[(?:modifies-tests|refactor-tests)\]", re.IGNORECASE)


def _hunk_lines(diff_text, sign):
    """Yield the content of added (`+`) or removed (`-`) hunk lines, skipping the
    `+++`/`---` file headers so a filename never counts as a code change."""
    header = sign * 3
    for line in (diff_text or "").splitlines():
        if line.startswith(sign) and not line.startswith(header):
            yield line[1:]


def _count(pattern, lines):
    return sum(1 for ln in lines if pattern.search(ln))


def modifies_tests(title):
    """True when a task opts into test modification via a [modifies-tests] /
    [refactor-tests] tag, relaxing the 8.5 diff-guard for that task only."""
    return bool(_TESTS_TAG.search(title or ""))


def is_suppressing_diff(diff_text):
    """Classify a unified diff as coverage-suppressing (spec 8.5). Pure text
    classifier over the `+`/`-` hunk lines only (never the `+++`/`---` headers).

    True when the diff nets a suppression marker (skip/xfail/@ts-ignore/
    # type: ignore/# noqa/eslint-disable) or nets a removed assertion. Uses net
    counts so an in-place edit (a marker/assertion present on both sides, or an
    assertion whose expected value merely changed) is not flagged -- only a real
    silencing or deletion is."""
    added = list(_hunk_lines(diff_text, "+"))
    removed = list(_hunk_lines(diff_text, "-"))
    if _count(_SUPPRESSION_MARKER, added) > _count(_SUPPRESSION_MARKER, removed):
        return True
    if _count(_ASSERTION, removed) > _count(_ASSERTION, added):
        return True
    return False


# ---------------------------------------------------------------- acceptance enforcement
# Spec §8.6: a task may carry an @acceptance(<criterion>) marker (parsed upstream into
# task.acceptance). "Green" is not enough -- the model could satisfy the gate without
# ever pinning the criterion in a test. acceptance_tokens mines a criterion for the
# test identifiers it names (test_* function/node ids, .py file paths); acceptance_in_diff
# then checks the attempt's diff for at least one of them on an ADDED line. A criterion
# naming no such tokens is advisory-only (no enforceable handle), so it never blocks.
# Both transforms are pure over the criterion + diff text, so the logic is unit-testable.
_ACCEPTANCE_TEST_FN = re.compile(r"test_\w+")
_ACCEPTANCE_PY_PATH = re.compile(r"[\w./\\-]+\.py\b")


def acceptance_tokens(criterion):
    """Extract test-identifying tokens from an acceptance-criterion string (spec §8.6):
    pytest function names / node ids matching a `test_` name, and file paths ending
    `.py`. Pure; returns a de-duplicated list preserving first appearance (paths first,
    then test names). An empty/None criterion or one naming no such token yields []."""
    text = criterion or ""
    tokens = []
    for pattern in (_ACCEPTANCE_PY_PATH, _ACCEPTANCE_TEST_FN):
        for m in pattern.finditer(text):
            tok = m.group(0)
            if tok not in tokens:
                tokens.append(tok)
    return tokens


def acceptance_in_diff(diff_text, criterion):
    """True when at least one acceptance_tokens(criterion) token appears on an ADDED
    line of the diff (spec §8.6). Pure text check over the `+` hunk lines only (never
    the `+++` header, `-` removals, or context). A criterion with no extractable tokens
    returns False -- callers treat that no-token case as advisory (see process_task)."""
    tokens = acceptance_tokens(criterion)
    if not tokens:
        return False
    added = "\n".join(_hunk_lines(diff_text, "+"))
    return any(tok in added for tok in tokens)


# ---------------------------------------------------------------- non-codifiable-acceptance routing
# Spec §8.6: an acceptance criterion is only ENFORCEABLE when it names something the
# harness can mechanically check -- a test identifier (acceptance_tokens) or a
# runnable-command signal (a known runner/verb). Purely subjective prose ("looks
# clean", "feels responsive") gives the harness no handle, so auto-mode must NOT guess
# a green: it refuses the task at pick time, routes it to a human checkpoint, and moves
# on to the rest of the backlog. This is a ROUTING decision, distinct from the
# acceptance ENFORCEMENT branch in process_task (which fires only for codifiable,
# test-named criteria). Both helpers are pure so the decision is unit-testable.
_RUNNABLE_SIGNAL = re.compile(
    r"""
      \bpytest\b | \bpython\b | \bnpm\b | \bpnpm\b   # known test/build runners
    | \bruff\b | \bmake\b
    | (?:^|\s)\./                                     # a leading ./ script invocation
    | `[^`]+`                                         # a backtick-wrapped command
    | \bexit\s+0\b | \breturns\s+0\b | \bpasses\b     # explicit success phrasing
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_codifiable_acceptance(criterion):
    """True when an acceptance criterion names something the harness can mechanically
    verify (spec §8.6): either it names a test (acceptance_tokens is non-empty) OR it
    carries a runnable-command signal -- a known runner/verb (pytest/python/npm/pnpm/
    ruff/make), a leading `./`, a backtick-wrapped command, or an explicit success
    phrase (exit 0 / returns 0 / passes). False for empty/None or purely subjective
    prose that names no such handle. Pure."""
    text = criterion or ""
    if not text.strip():
        return False
    if acceptance_tokens(text):
        return True
    return bool(_RUNNABLE_SIGNAL.search(text))


def needs_human_checkpoint(task):
    """True when a task carries an acceptance criterion the harness cannot codify
    (spec §8.6): auto-mode refuses to guess at subjective acceptance and routes the
    task to a human checkpoint instead. False when the task has no acceptance or a
    codifiable one. Pure decision over the task, so the pick-time routing is
    unit-testable without a run."""
    acceptance = getattr(task, "acceptance", None)
    return bool(acceptance) and not is_codifiable_acceptance(acceptance)


# ---------------------------------------------------------------- oversize guard (scope drift)
# Spec §8.7: scoping is owned up front, but the harness already holds the diff and
# retry count, so for zero extra tokens it can catch drift. When a task is about to
# be blocked (retries exhausted or no-progress), if its last attempt's diff spans
# more distinct files than the threshold, the block reason becomes the actionable
# "likely too large — split needed" instead of a bare gate/stuck message.
DEFAULT_OVERSIZE_FILE_THRESHOLD = 25


def _changed_files(diff_text):
    """Distinct file paths touched by a unified diff. Reads the file HEADERS only
    -- the `diff --git a/… b/…` line (one per file), falling back to a `+++ b/…`
    header -- and NEVER the `+`/`-` content lines, so a `+added line` of code is
    never miscounted as a new file. A set dedups the two header sources."""
    files = set()
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            path = line.split()[-1]
            files.add(path[2:] if path.startswith("b/") else path)
        elif line.startswith("+++ "):
            path = line[4:].strip()
            if path != "/dev/null":
                files.add(path[2:] if path.startswith("b/") else path)
    return files


def is_oversize_diff(diff_text, threshold):
    """True when a unified diff touches MORE distinct files than `threshold`
    (spec §8.7 mechanical oversize guard). Pure: counts file headers, never the
    `+`/`-` content lines. At-or-under the threshold is not oversize."""
    return len(_changed_files(diff_text)) > threshold


def _oversize_reason(base_reason, diff_text, threshold):
    """Sharpen a block reason (spec §8.7): when the last attempt's diff exceeds the
    file-count threshold the task is likely mis-scoped, so return the actionable
    "split needed" message instead of the bare gate/stuck reason."""
    if is_oversize_diff(diff_text, threshold):
        return "likely too large — split needed"
    return base_reason


# ---------------------------------------------------------------- protected-paths guard
# Spec §9: some paths are off-limits to the autonomous loop -- secrets, CI config,
# lockfiles. touches_protected classifies an attempt's committed diff: it reads the
# changed file HEADERS only (via _changed_files, never the `+`/`-` content) and matches
# each path against each configured glob. A pattern ending in `/**` is a recursive
# prefix (the prefix dir itself or anything under it); every other pattern uses fnmatch
# glob semantics. Empty patterns never matches, so the guard is opt-in. Pure over the
# diff + patterns, so unit-testable without a repo. The harness rejects an otherwise-green
# attempt whose committed diff touches a protected path (see process_task).
def touches_protected(diff_text, patterns):
    """True when any file changed in `diff_text` matches any glob in `patterns`
    (spec §9). Reads the diff's file headers only (via _changed_files), never the
    `+`/`-` content. A pattern ending in `/**` is a recursive prefix: a path matches
    when it equals the prefix or starts with `prefix + "/"`. Any other pattern is
    matched with fnmatch.fnmatch. Empty `patterns` never matches. Pure."""
    if not patterns:
        return False
    for path in _changed_files(diff_text):
        for pat in patterns:
            if pat.endswith("/**"):
                prefix = pat[:-3]
                if path == prefix or path.startswith(prefix + "/"):
                    return True
            elif fnmatch.fnmatch(path, pat):
                return True
    return False


# ---------------------------------------------------------------- forward-flag (scope drift)
# Spec §8.7 (semantic backstop, complements the mechanical oversize guard): the agent
# that JUST finished a task appends one line to its commit body --
# `LOOP-FLAG: <what changed>` -- when its work invalidated a LATER task's premise
# (e.g. "changed the User model shape"). The harness harvests these from the commit
# and surfaces them to subsequent tasks' prompts. Purely advisory + near-zero cost:
# usually there are none (empty notice -> zero prompt bytes), and the current working
# agent never re-validates its own scope. Both transforms are pure. v1 accumulates
# flags (deduped + bounded) across the run rather than mapping each to a specific
# target task -- a bounded heads-up that never misses the target.
FORWARD_FLAG_LIMIT = 10
_FORWARD_FLAG = re.compile(r"^[ \t]*LOOP-FLAG:[ \t]*(.+?)[ \t]*$", re.IGNORECASE | re.MULTILINE)


def parse_forward_flags(commit_body):
    """Extract forward-flag lines from a commit body (spec §8.7): each
    `LOOP-FLAG: <what changed>` line becomes one whitespace-trimmed flag string.
    Pure. Empty/None body or no markers -> []."""
    return [m.group(1).strip() for m in _FORWARD_FLAG.finditer(commit_body or "")
            if m.group(1).strip()]


def format_flag_notice(flags):
    """Render pending forward-flags (spec §8.7) as a lean prompt heads-up, or '' when
    there are none (the common case, so zero prompt cost). Advisory only: the working
    agent adapts if a flag affects it but never re-validates scope."""
    flags = [str(f).strip() for f in (flags or []) if str(f).strip()]
    if not flags:
        return ""
    lines = "\n".join(f"- {f}" for f in flags)
    return ("\n\nHeads-up from earlier tasks (an earlier change may affect this "
            "task's premise; adapt if needed, do not re-scope):\n" + lines)


# ---------------------------------------------------------------- rate-limit backoff
# Spec §9: a rate-limit rejection is NOT a task failure. When Claude's usage/rate
# limit rejects an attempt the request never ran -- counting it as a gate failure
# would burn retries and falsely mark the task "blocked" (which resume then skips,
# corrupting the run). Instead the harness discards any in-flight work (atomicity),
# then per `on_rate_limit`: "pause-resume" (default) sleeps until the limit resets
# and re-runs the SAME attempt (no retry consumed, consecutive_failures untouched);
# "halt" -- or a wait beyond max_rate_limit_wait_s -- stops the loop cleanly with
# resume instructions. Pure helpers (is_rate_limited / rate_limit_reset /
# wait_seconds / handle_rate_limit) take `now` in and never sleep, so the logic is
# unit-testable without wall-clock waits.
RATE_LIMIT_BUFFER_S = 15                 # cushion so we retry just AFTER the reset
DEFAULT_MAX_RATE_LIMIT_WAIT_S = 21600    # 6h: covers a five_hour reset, bounds garbage resetsAt

ClaudeResult = collections.namedtuple("ClaudeResult", "cost rate_limited resets_at")


class RateLimitHalt(Exception):
    """Stop the whole loop cleanly at a rate limit (on_rate_limit=halt, or wait >
    cap). The current task is discarded + left unmarked (todo) so a later resume
    retries it -- never marked blocked, since a rate limit is not the task's fault."""

    def __init__(self, resets_at):
        self.resets_at = resets_at
        super().__init__("rate limit reached")


def is_rate_limited(events):
    """True when a session was rejected for a usage/rate limit (spec §9), not a
    normal gate/task failure. Two independent stream-json signals, either
    sufficient (both appear on an org five-hour-limit rejection):
      - a rate_limit_event whose rate_limit_info.status == "rejected"
      - the terminal result event with api_error_status == 429"""
    for ev in events:
        if ev.get("type") == "rate_limit_event":
            if (ev.get("rate_limit_info") or {}).get("status") == "rejected":
                return True
        if ev.get("type") == "result" and ev.get("api_error_status") == 429:
            return True
    return False


def rate_limit_reset(events):
    """Unix-epoch resetsAt from the (last) rejected rate_limit_event, or None when
    absent -- e.g. a bare 429 result carrying no reset hint."""
    resets = None
    for ev in events:
        if ev.get("type") != "rate_limit_event":
            continue
        info = ev.get("rate_limit_info") or {}
        if info.get("status") == "rejected" and info.get("resetsAt") is not None:
            resets = info["resetsAt"]
    return resets


def wait_seconds(resets_at, now, buffer_s=RATE_LIMIT_BUFFER_S):
    """Seconds to sleep until a rate limit resets (spec §9). Pure: `now` is passed
    in (never time.time()) so tests pin the arithmetic without sleeping. Returns
    max(0, resets_at - now) + buffer; a missing or already-past resetsAt yields just
    the buffer (a short courtesy wait, never negative)."""
    base = 0 if resets_at is None else max(0, int(resets_at) - int(now))
    return base + buffer_s


def handle_rate_limit(result, cfg, now):
    """Decide pause vs halt for a rate-limited attempt (spec §9). Returns the
    seconds to sleep under pause-resume; raises RateLimitHalt when on_rate_limit is
    "halt" or the wait would exceed max_rate_limit_wait_s. Pure w.r.t. time (`now`
    passed in, no sleeping here) so the decision is unit-testable."""
    if cfg.get("on_rate_limit", "pause-resume") == "halt":
        raise RateLimitHalt(result.resets_at)
    wait = wait_seconds(result.resets_at, now)
    cap = cfg.get("max_rate_limit_wait_s", DEFAULT_MAX_RATE_LIMIT_WAIT_S)
    if cap is not None and wait > cap:
        raise RateLimitHalt(result.resets_at)
    return wait


def _rate_limit_halt_msg(resets_at):
    """Human resume instruction for a rate-limit halt (report banner + stdout)."""
    when = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(resets_at))
            if resets_at else "the limit resets")
    return (f"rate limit reached -- halted cleanly. Resume with "
            f"`python .loop/orchestrator.py` after {when}.")


def _announce_rate_limit_pause(resets_at, wait, state, tasks):
    """Log a pending pause to stdout + activity.log + a transient report banner."""
    when = time.strftime("%H:%M:%S", time.localtime(resets_at)) if resets_at else "?"
    msg = f"rate limit hit -- pausing {wait}s (~{wait // 60}m), resumes ~{when}"
    print(f"[loop] {msg}")
    _append_activity(f"⏳ {msg}")
    write_report(state, tasks, note=msg)


# ---------------------------------------------------------------- learned conventions
# Spec §16: a rolling, bounded, deduped `.loop/learned.md` of repo-specific
# conventions the loop discovers (e.g. "use pnpm"), injected into later iterations.
# Bounded + additive-only so it never bloats or rewrites the core prompt. The two
# transforms are pure so the dedup/bound logic is unit-testable without touching
# disk; append_learned is the thin IO wrapper (read -> append -> normalize -> write).
DEFAULT_LEARNED_LIMIT = 15


def format_learned_bullet(text):
    """Normalize a learned convention into ONE `- `-prefixed markdown bullet with
    all interior whitespace (spaces, tabs, newlines) collapsed to single spaces
    (spec §16). Any existing leading `-`/`*` list marker is stripped first, so the
    function is idempotent -- re-formatting an already-formatted bullet is a no-op."""
    collapsed = " ".join((text or "").split())
    collapsed = re.sub(r"^[-*]\s+", "", collapsed)
    return f"- {collapsed}"


def dedupe_bounded(bullets, limit=DEFAULT_LEARNED_LIMIT):
    """Dedupe a bullet list keeping the MOST-RECENT occurrence of each duplicate,
    then cap to the last `limit` bullets (spec §16 anti-degradation). Pure. A repeat
    bullet is re-surfaced at its latest position (so a re-learned convention stays
    fresh), and only the newest `limit` survive so the layer never bloats."""
    seen = set()
    kept = []
    for b in reversed(bullets):            # walk newest-first: first sight wins
        if b not in seen:
            seen.add(b)
            kept.append(b)
    kept.reverse()                         # restore original (latest-occurrence) order
    return kept[-limit:]


def _read_learned_bullets(path):
    """Existing non-blank bullet lines from a learned.md, or [] when absent."""
    p = Path(path)
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def append_learned(path, bullet):
    """Append one learned convention to the rolling `.loop/learned.md` (spec §16),
    then rewrite it deduped + bounded. Reads any existing bullets, adds the
    normalized new one, keeps the most-recent of duplicates, and caps the file to
    DEFAULT_LEARNED_LIMIT. Returns the bullets written."""
    bullets = _read_learned_bullets(path)
    bullets.append(format_learned_bullet(bullet))
    bullets = dedupe_bounded(bullets)
    Path(path).write_text("\n".join(bullets) + "\n", encoding="utf-8")
    return bullets


# §16 capture: on a gate-failure -> green recovery, mine the FAILURE tail for a
# reusable, repo-environmental friction (missing module/tool, unrecognized command)
# and record it. Deliberately narrow -- one-off task bugs (a failed assertion, a
# lint rule) are NOT conventions, so they yield None and never pollute learned.md.
# Each signal maps a recognized error to a short, generalizable convention hint.
_LEARN_SIGNALS = [
    (re.compile(r"No module named ['\"]([\w.]+)['\"]"),
     "python module `{0}` is required -- ensure it is installed/declared before use"),
    (re.compile(r"Cannot find module ['\"]([^'\"]+)['\"]"),
     "node module `{0}` is required -- ensure it is installed before use"),
    (re.compile(r"([^\s:'\"]+): command not found"),
     "`{0}` is not on PATH -- install it or invoke the correct command"),
    (re.compile(r"[Tt]he term ['\"]?([\w.\-]+)['\"]? is not recognized"),
     "`{0}` is not recognized here -- install it or use the correct command"),
]


def learned_from_failure(gate_failure_tail):
    """Pure heuristic (spec §16): scan a gate-failure tail for a REUSABLE,
    repo-environmental friction signal (missing module/tool, unrecognized command)
    and return a one-line convention hint, or None when the failure is a one-off
    task bug not worth remembering. Narrow by design so the injected learned layer
    stays lean and generalizable -- task-specific assertion/lint failures never
    become bullets. Returns the FIRST matching signal for determinism."""
    text = gate_failure_tail or ""
    for pattern, template in _LEARN_SIGNALS:
        m = pattern.search(text)
        if m:
            return template.format(m.group(1))
    return None


def _capture_learned(gate_failure_tail, path=LEARNED):
    """On a gate-failure -> green recovery, mine the failure for a reusable
    convention and append it to learned.md (spec §16). No-op (returns None) when
    there was no prior gate failure this task, or the heuristic finds nothing
    reusable -- so learned.md only grows on genuine, generalizable friction."""
    if not gate_failure_tail:
        return None
    bullet = learned_from_failure(gate_failure_tail)
    if bullet:
        append_learned(str(path), bullet)
    return bullet


def _learned_flag(path=LEARNED):
    """Return the ` --append-system-prompt-file <path>` fragment injecting the
    rolling learned conventions into a claude run (spec §16), or '' when the file
    is absent or blank. Only a non-empty learned.md is injected, so early iterations
    (before anything is learned) add nothing. Reads the file but returns just the
    flag fragment, so the wiring is unit-testable without spawning claude."""
    p = Path(path)
    try:
        if p.exists() and p.read_text(encoding="utf-8").strip():
            return f' --append-system-prompt-file "{p}"'
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------- budget cap
# Spec §9: a hard dollar ceiling on cumulative best-effort cost. Opt-in -- a None /
# 0 / negative `budget.max_cost_usd` means no cap. Checked ONLY at the task boundary
# (before pick_task), never mid-task, so a running attempt always finishes atomically
# (the atomicity invariant): clean worktree <=> between tasks. Pure so the threshold
# logic is unit-testable without a run.
def over_budget(cost_usd, cap):
    """True when a positive dollar cap is set and cumulative spend has reached it
    (spec §9). A None / 0 / negative cap means "no cap" -> always False, so the
    guard is opt-in. Pure."""
    if cap is None or cap <= 0:
        return False
    return cost_usd >= cap


def avg_task_cost(cost_usd, tasks_done):
    """Mean best-effort cost of a completed task so far (spec §9 projection input).
    Pure. Returns 0.0 when no task has completed yet (tasks_done <= 0) so the first
    boundary has no average to project with -- the guard then reduces to the plain
    over_budget check."""
    if tasks_done <= 0:
        return 0.0
    return cost_usd / tasks_done


def projected_over_budget(cost_so_far, avg_cost, cap):
    """True when starting one more ~average-cost task would breach the dollar cap
    (spec §9): never START a task whose projected end-cost exceeds the cap. A None /
    0 / negative cap means "no cap" -> always False (opt-in, mirrors over_budget).
    Pure: `avg_cost` is supplied by avg_task_cost so the projection is unit-testable."""
    if cap is None or cap <= 0:
        return False
    return cost_so_far + avg_cost > cap


def over_wallclock(started_epoch, now_epoch, max_minutes):
    """True when a positive wall-clock cap is set and the run's elapsed time has
    reached it (spec §9). A None / 0 / negative `max_minutes` means "no cap", and a
    missing/None `started_epoch` (older state predating the field) also degrades to
    no-cap -> always False, so the guard is opt-in and resume-safe. Like the dollar
    cap, checked ONLY at the task boundary so a running attempt finishes atomically.
    Pure: `now_epoch` is passed in (never time.time()) so the arithmetic is
    unit-testable without sleeping."""
    if max_minutes is None or max_minutes <= 0 or not started_epoch:
        return False
    return now_epoch - started_epoch >= max_minutes * 60


# ---------------------------------------------------------------- main loop
def process_task(task, cfg, adapter, state, backlog_rel):
    """Run one task through up to max_retries attempts. Returns (done, sha, reason)."""
    gate = cfg["gate"]
    max_retries = cfg.get("budget", {}).get("max_retries", 3)
    before = head_sha()
    prior = None
    prev_diff = None
    cur_diff = None
    last_gate_fail = None   # tail of the most-recent GATE failure, for §16 capture
    oversize_threshold = cfg.get("oversize_file_threshold", DEFAULT_OVERSIZE_FILE_THRESHOLD)
    patterns = cfg.get("guardrails", {}).get("protected_paths", [])
    model = pick_model(task, cfg)
    flags = state.get("forward_flags") or []   # §8.7 flags raised by earlier tasks

    for attempt in range(1, max_retries + 1):
        n = state["iterations"] + 1
        logfile = LOGDIR / f"iteration-{n:03d}-a{attempt}.md"
        print("[loop] " + task_banner(task, attempt, max_retries, model,
                                       state.get("cost_usd", 0.0)))

        prompt = build_prompt(task, gate, prior, flags=flags)
        label = f"{task.id} attempt {attempt}/{max_retries}: {task.title[:60]}"
        # Run the attempt, pausing through any rate-limit rejection WITHOUT consuming
        # a retry or counting a failure (spec §9). handle_rate_limit raises
        # RateLimitHalt (caught in main) when policy is halt or the wait exceeds cap.
        while True:
            result = run_claude(prompt, cfg, logfile, model=model, label=label)
            state["cost_usd"] = state.get("cost_usd", 0.0) + result.cost
            if not result.rate_limited:
                break
            discard_inflight(before, backlog_rel)      # keep atomicity while paused
            wait = handle_rate_limit(result, cfg, time.time())
            _announce_rate_limit_pause(result.resets_at, wait, state, adapter.list())
            save_state(state)                           # persist cost before the sleep
            time.sleep(wait)

        cur_diff = git("diff", before)          # what the model changed this attempt
        new_commit = head_sha() != before
        dirty = working_dirty({backlog_rel})

        if new_commit and not dirty:
            ok, gate_out = run_gate(gate)
            if ok and is_suppressing_diff(cur_diff) and not modifies_tests(task.title):
                # Green but gamed: the diff weakens the gate (spec 8.5). Reject the
                # attempt, discard it, and make the model solve the task honestly.
                prior = (
                    "Rejected: the gate passed but your diff weakens it -- it adds a "
                    "skip/xfail/@ts-ignore/# type: ignore/# noqa/eslint-disable marker "
                    "or removes an assertion. Solve the task without suppressing checks. "
                    "If this task legitimately edits tests, its title must be tagged "
                    "[modifies-tests]."
                )
            elif (
                ok
                and getattr(task, "acceptance", None)
                and acceptance_tokens(task.acceptance)
                and not acceptance_in_diff(cur_diff, task.acceptance)
            ):
                # Green but the acceptance test is missing (spec §8.6): the gate
                # passed yet the diff adds no test pinning the criterion. Reject the
                # attempt so the model adds the test that would fail on regression.
                prior = (
                    "Rejected: the gate passed but your diff adds no test pinning the "
                    "acceptance criterion. Add a test that exercises and pins this "
                    "criterion so a future regression would fail the gate: "
                    f"{task.acceptance}"
                )
            elif ok and touches_protected(cur_diff, patterns):
                # Green but the diff modifies a protected path (spec §9). Reject the
                # attempt so the model solves the task without touching files it must
                # not change -- mirrors the suppressing-diff rejection.
                prior = (
                    "Rejected: the gate passed but your diff modifies a protected "
                    "path. This task must not modify: " + ", ".join(patterns) + ". "
                    "Solve the task without changing those files."
                )
            elif ok:
                # Green. §16: if we recovered from a prior gate failure, mine it
                # for a reusable repo convention before committing.
                _capture_learned(last_gate_fail)
                adapter.mark_done(task)                 # check the box in BACKLOG.md
                git("add", backlog_rel)
                git("commit", "--amend", "--no-edit")   # fold checkbox into the task commit
                return True, head_sha(), None
            else:
                last_gate_fail = gate_out               # §16 capture source on recovery
                prior = gate_out
        elif not new_commit:
            prior = "No commit was produced. You must commit your work."
        else:  # committed but left the tree dirty
            prior = "Uncommitted changes remained after your commit. Commit everything in one commit."

        stuck = no_progress(prev_diff, cur_diff)
        prev_diff = cur_diff
        discard_inflight(before, backlog_rel)
        if stuck:
            reason = "no progress across retries (identical diff) — likely stuck"
            return False, None, _oversize_reason(reason, cur_diff, oversize_threshold)
        model = escalate(model, cfg)   # next retry climbs one tier (spec §8.4)

    reason = (prior or "gate never passed")[:500]
    return False, None, _oversize_reason(reason, cur_diff, oversize_threshold)


# ---------------------------------------------------------------- subcommands
def cmd_stop(loop=LOOP):
    """Drop the STOP sentinel so a running loop halts at the next task boundary.

    No signal handling / PID-hunting: a running orchestrator checks for this file
    every iteration and exits cleanly (see the main loop). Returns an exit code."""
    if not loop.exists():
        print(f"[loop] no .loop/ at {loop.parent}. nothing to stop.")
        return 1
    stop = loop / "STOP"
    stop.write_text("", encoding="utf-8")
    print(f"[loop] wrote {stop}. loop will halt at the next task boundary.")
    return 0


def cmd_status(report=REPORT):
    """Print the live report, or a notice if no run has produced one yet."""
    if report.exists():
        print(report.read_text(encoding="utf-8"), end="")
        return 0
    print(f"[loop] no run yet (no {report}).")
    return 0


def main():
    if not LOOP.exists():
        print(f"[loop] no .loop/ at {ROOT}. run the nocturne skill first.")
        sys.exit(1)
    if not CONFIG.exists():
        print(f"[loop] missing {CONFIG}.")
        sys.exit(1)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    global LIVE_FEED
    LIVE_FEED = cfg.get("observability", {}).get("live_feed", True)
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
                "started_epoch": time.time(),
            }
        state["pid"] = os.getpid()
        ensure_branch(state["branch"])
        save_state(state)
        _append_activity(f"\n═══ loop {state['branch']} · started {time.strftime('%H:%M:%S')} ═══")

        max_iter = cfg.get("budget", {}).get("max_iterations", 50)
        max_consec = cfg.get("budget", {}).get("max_consecutive_failures", 3)
        cap = cfg.get("budget", {}).get("max_cost_usd")
        max_wallclock_min = cfg.get("budget", {}).get("max_wallclock_min")
        started_epoch = state.get("started_epoch")   # None on pre-field state -> no cap

        # Baseline-green preflight (dogfood #6): run the gate ONCE before any task
        # starts. A red baseline means pre-existing failures -- the first task
        # would inherit them and be falsely blocked. Halt up front, no task churn.
        base_ok, base_tail = run_gate(cfg["gate"])
        baseline_halt = baseline_halt_reason(
            base_ok, base_tail, cfg.get("require_green_baseline", True))

        while True:
            if baseline_halt:
                halt = baseline_halt
                break
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
            if over_budget(state["cost_usd"], cap):
                halt = f"budget cap reached (${state['cost_usd']:.4f} / ${cap:.2f})"
                break
            # §9 projection: never START a task whose projected end-cost (spend so far
            # + the running average task cost) would breach the cap. On the first task
            # done_count is 0 so avg is 0 and this reduces to the over_budget case above.
            done_count = sum(1 for r in state["results"].values() if r.get("status") == "done")
            avg = avg_task_cost(state["cost_usd"], done_count)
            if projected_over_budget(state["cost_usd"], avg, cap):
                halt = (f"projected budget cap reached (${state['cost_usd']:.4f} + "
                        f"~${avg:.4f}/task > ${cap:.2f})")
                break
            if over_wallclock(started_epoch, time.time(), max_wallclock_min):
                elapsed_min = (time.time() - started_epoch) / 60
                halt = f"wall-clock cap reached ({elapsed_min:.0f}m / {max_wallclock_min:.0f}m)"
                break

            task = pick_task(adapter, state)
            if task is None:
                halt = "backlog empty"
                break

            # §8.6 non-codifiable-acceptance routing: a task whose acceptance criterion
            # names no mechanically-checkable handle (test id or runnable command) can't
            # be verified by the harness, so auto-mode refuses to guess a green. Mark it
            # blocked for a human checkpoint and continue the rest of the backlog. This
            # is a ROUTING decision, not a task failure -- consecutive_failures untouched.
            if needs_human_checkpoint(task):
                state["results"][task.id] = {
                    "status": "blocked",
                    "reason": "acceptance not codifiable — needs a human checkpoint",
                    "title": task.title,
                    "retries": 0,
                }
                print(f"[loop] CHECKPOINT {task.id}")
                state["iterations"] += 1
                save_state(state)
                write_report(state, adapter.list())
                continue

            try:
                done, sha, reason = process_task(task, cfg, adapter, state, backlog_rel)
            except RateLimitHalt as rl:
                # Rate limit, not a task failure: discard in-flight, leave the task
                # unmarked (todo) so a later resume retries it, and stop cleanly.
                discard_inflight(head_sha(), backlog_rel)
                halt = _rate_limit_halt_msg(rl.resets_at)
                break
            if done:
                state["results"][task.id] = {"status": "done", "commit": sha,
                                             "title": task.title}
                state["consecutive_failures"] = 0
                print(f"[loop] DONE {task.id} -> {sha[:9]}")
                # §8.7 forward-flag: harvest any LOOP-FLAG lines the finished
                # agent left in its commit and surface them to later tasks.
                new_flags = parse_forward_flags(git("log", "-1", "--format=%B", sha))
                if new_flags:
                    state["forward_flags"] = dedupe_bounded(
                        (state.get("forward_flags") or []) + new_flags,
                        limit=FORWARD_FLAG_LIMIT,
                    )
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

            # section 9 checkpoint modes: after a DONE task (never a blocked one), the
            # state is saved + the report written, so pausing here is clean + resumable
            # -- the next run picks up at the next todo. Only pause when there IS a next
            # task and `mode` calls for a boundary here (see should_checkpoint).
            if done:
                mode = cfg.get("mode", "auto")
                nxt = pick_task(adapter, state)
                if should_checkpoint(mode, task, nxt):
                    halt = (f"checkpoint ({mode}): task {task.id} done -- resume with "
                            f"'python .loop/orchestrator.py' to continue")
                    break

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
    _cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if _cmd == "stop":
        sys.exit(cmd_stop())
    elif _cmd == "status":
        sys.exit(cmd_status())
    elif _cmd == "run":
        main()
    else:
        print(f"[loop] unknown command: {_cmd!r}. use: run | stop | status")
        sys.exit(2)
