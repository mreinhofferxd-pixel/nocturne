"""Read-side status viewer for the nocturne global run registry.

Standalone stdlib-only module: reads the heartbeat json files the
orchestrator writes under $NOCTURNE_HOME/runs/ (default ~/.nocturne/runs/)
and renders them as a one-line statusline or aligned watch rows. It never
imports the orchestrator, so it works from any shell or statusline hook
without a run's worktree on sys.path.
"""
import json
import os
import sys
import time
from pathlib import Path

STALE_AFTER_S = 900
TERMINAL = {"halted", "done"}
GLYPHS = {
    "running": "▶",   # arrow
    "paused": "⏳",    # hourglass
    "done": "■",      # square
    "halted": "✖",    # cross
    "stale": "?",
}


def default_runs_dir(env=None):
    home = (env or os.environ).get("NOCTURNE_HOME")
    return (Path(home) if home else Path.home() / ".nocturne") / "runs"


def load_records(runs_dir):
    """All parseable heartbeat records under runs_dir, unordered. Unreadable
    or invalid files are dropped silently -- a torn write from a concurrent
    heartbeat must not break the viewer. Missing dir yields []."""
    records = []
    try:
        paths = sorted(Path(runs_dir).glob("*.json"))
    except OSError:
        return []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def classify_run(record, now, stale_after_s=STALE_AFTER_S):
    """Effective status of one record: terminal statuses pass through, live
    ones ("running"/"paused") whose heartbeat is older than stale_after_s
    become "stale" -- a crashed loop must not report "running" forever."""
    status = record.get("status")
    if status in TERMINAL:
        return status
    if status in ("running", "paused"):
        if now - (record.get("updated_at") or 0) > stale_after_s:
            return "stale"
        return status
    return status


def _by_recency(records):
    return sorted(records, key=lambda r: r.get("updated_at") or 0, reverse=True)


def _strip_model(model):
    if not model:
        return "-"
    return model[7:] if model.startswith("claude-") else model


def _task_field(record):
    if not record.get("task_id"):
        return "-"
    return f"{record['task_id']} a{record.get('attempt')}"


def _age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def status_line(records, now):
    """One statusline string: idle marker, running count, up to 3 active-run
    segments (most recent first), overflow count, then paused/stale counts."""
    if not records:
        return "nocturne: idle"
    classified = [(classify_run(r, now), r) for r in _by_recency(records)]
    active = [r for status, r in classified if status == "running"]
    parts = [f"nocturne: {len(active)} running"]
    for r in active[:3]:
        parts.append(
            f"{r.get('run_id')} {_task_field(r)} "
            f"{_strip_model(r.get('model'))} ${r.get('cost_usd') or 0.0:.2f}")
    if len(active) > 3:
        parts.append(f"+{len(active) - 3} more")
    for bucket in ("paused", "stale"):
        n = sum(1 for status, _ in classified if status == bucket)
        if n:
            parts.append(f"{n} {bucket}")
    return " · ".join(parts)


def watch_rows(records, now):
    """One aligned text row per record, most recently updated first:
    glyph, run_id, task+attempt, model, cost, done/blocked/todo, age."""
    cells = []
    for r in _by_recency(records):
        cells.append((
            GLYPHS.get(classify_run(r, now), "?"),
            str(r.get("run_id") or "-"),
            _task_field(r),
            str(r.get("model") or "-"),
            f"${r.get('cost_usd') or 0.0:.2f}",
            f"{r.get('done') or 0}/{r.get('blocked') or 0}/{r.get('todo') or 0}",
            _age(now - (r.get("updated_at") or 0)),
        ))
    if not cells:
        return []
    widths = [max(len(row[i]) for row in cells) for i in range(len(cells[0]))]
    return ["  ".join(col.ljust(w) for col, w in zip(row, widths)).rstrip()
            for row in cells]


def _print_rows(runs_dir):
    rows = watch_rows(load_records(runs_dir), time.time())
    print("\n".join(rows) if rows else "nocturne: idle", flush=True)


def main(argv=None):
    # Windows: piped stdout defaults to cp1252, which cannot encode the row
    # glyphs -- force UTF-8 with replacement so a statusline hook or pipe
    # consumer never sees a UnicodeEncodeError crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    runs_dir = default_runs_dir()
    if argv[:1] == ["--line"]:
        print(status_line(load_records(runs_dir), time.time()))
    elif argv[:1] == ["--watch"]:
        interval = float(argv[1]) if len(argv) > 1 else 2.0
        try:
            while True:
                _print_rows(runs_dir)
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
    else:
        _print_rows(runs_dir)


if __name__ == "__main__":
    main()
