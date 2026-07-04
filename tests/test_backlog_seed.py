"""Backlog-seed preflight (dogfood #6): an uncommitted backlog is committed on
its own before the task loop, so the first done task's checkbox --amend never
folds unrelated backlog edits into that task's commit."""
from orchestrator import _porcelain_paths, needs_backlog_seed


def test_untracked_backlog_needs_seed():
    raw = "?? BACKLOG.md\n"
    assert needs_backlog_seed(_porcelain_paths(raw), "BACKLOG.md") is True


def test_modified_backlog_needs_seed():
    raw = " M BACKLOG.md\n"
    assert needs_backlog_seed(_porcelain_paths(raw), "BACKLOG.md") is True


def test_clean_committed_backlog_no_seed():
    assert needs_backlog_seed(_porcelain_paths(""), "BACKLOG.md") is False


def test_unrelated_dirty_path_no_seed():
    raw = " M src/app.py\n?? notes.txt\n"
    assert needs_backlog_seed(_porcelain_paths(raw), "BACKLOG.md") is False


def test_backlog_among_other_paths_needs_seed():
    raw = " M src/app.py\n?? NOCTURNE_BACKLOG.md\n"
    assert needs_backlog_seed(_porcelain_paths(raw), "NOCTURNE_BACKLOG.md") is True


def test_no_partial_name_match():
    # a different file whose name merely contains the backlog name must not seed
    raw = "?? OLD_BACKLOG.md.bak\n"
    assert needs_backlog_seed(_porcelain_paths(raw), "BACKLOG.md") is False
