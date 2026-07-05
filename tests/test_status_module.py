"""Read-side status module: staleness classification, statusline capping,
watch-row glyphs/ages/alignment, and torn-file tolerance in load_records."""
import json

import nocturne_status as ns

NOW = 10_000.0


def rec(**kw):
    base = {
        "run_id": "repo-x", "root": "/repo", "branch": "loop/x", "pid": 1,
        "status": "running", "task_id": "task-1", "task_title": "t",
        "attempt": 1, "model": "claude-fable-5", "cost_usd": 1.234,
        "done": 3, "blocked": 1, "todo": 4, "updated_at": NOW - 10,
    }
    base.update(kw)
    return base


# ------------------------------------------------------------ classify_run

def test_fresh_running_stays_running():
    assert ns.classify_run(rec(), NOW) == "running"


def test_old_running_goes_stale():
    assert ns.classify_run(rec(updated_at=NOW - 901), NOW) == "stale"


def test_fresh_paused_stays_paused():
    assert ns.classify_run(rec(status="paused"), NOW) == "paused"


def test_old_paused_goes_stale():
    assert ns.classify_run(rec(status="paused", updated_at=NOW - 5000), NOW) == "stale"


def test_terminal_statuses_pass_through_even_when_old():
    assert ns.classify_run(rec(status="done", updated_at=0), NOW) == "done"
    assert ns.classify_run(rec(status="halted", updated_at=0), NOW) == "halted"


def test_stale_after_s_override():
    assert ns.classify_run(rec(updated_at=NOW - 20), NOW, stale_after_s=10) == "stale"


# ------------------------------------------------------------- status_line

def test_status_line_idle_when_empty():
    assert ns.status_line([], NOW) == "nocturne: idle"


def test_status_line_single_run_segment():
    line = ns.status_line([rec()], NOW)
    assert line == "nocturne: 1 running · repo-x task-1 a1 fable-5 $1.23"


def test_status_line_caps_at_three_most_recent_plus_more():
    records = [rec(run_id=f"r{i}", updated_at=NOW - i) for i in range(4)]
    line = ns.status_line(records, NOW)
    assert line.startswith("nocturne: 4 running")
    assert "+1 more" in line
    for shown in ("r0", "r1", "r2"):
        assert shown in line
    assert "r3" not in line


def test_status_line_counts_paused_and_stale():
    records = [
        rec(),
        rec(status="paused"),
        rec(status="running", updated_at=NOW - 5000),
    ]
    line = ns.status_line(records, NOW)
    assert line.startswith("nocturne: 1 running")
    assert "1 paused" in line
    assert "1 stale" in line


# -------------------------------------------------------------- watch_rows

def test_watch_rows_glyphs_ages_and_recency_order():
    records = [
        rec(run_id="run-c", status="done", updated_at=NOW - 7200),
        rec(run_id="run-a", status="running", updated_at=NOW - 12),
        rec(run_id="run-e", status="running", updated_at=NOW - 5000),
        rec(run_id="run-b", status="paused", updated_at=NOW - 180),
        rec(run_id="run-d", status="halted", updated_at=NOW - 7300),
    ]
    rows = ns.watch_rows(records, NOW)
    assert len(rows) == 5
    assert rows[0].startswith("▶") and "run-a" in rows[0] and rows[0].endswith("12s")
    assert rows[1].startswith("⏳") and "run-b" in rows[1] and rows[1].endswith("3m")
    assert rows[2].startswith("?") and "run-e" in rows[2] and rows[2].endswith("1h")
    assert rows[3].startswith("■") and "run-c" in rows[3] and rows[3].endswith("2h")
    assert rows[4].startswith("✖") and "run-d" in rows[4] and rows[4].endswith("2h")
    assert "$1.23" in rows[0]
    assert "3/1/4" in rows[0]


def test_watch_rows_between_tasks_shows_dash():
    rows = ns.watch_rows([rec(task_id=None, attempt=None, model=None)], NOW)
    assert " -  " in rows[0]


def test_watch_rows_columns_align():
    rows = ns.watch_rows(
        [rec(run_id="short"), rec(run_id="a-much-longer-run-id")], NOW)
    assert len({row.index("$") for row in rows}) == 1


def test_watch_rows_empty():
    assert ns.watch_rows([], NOW) == []


# ------------------------------------------------------------ load_records

def test_load_records_missing_dir_is_empty(tmp_path):
    assert ns.load_records(tmp_path / "nope") == []


def test_load_records_drops_corrupt_keeps_valid(tmp_path):
    good = rec()
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "torn.json").write_text('{"run_id": "x", "sta', encoding="utf-8")
    (tmp_path / "notdict.json").write_text("[1, 2]", encoding="utf-8")
    assert ns.load_records(tmp_path) == [good]
