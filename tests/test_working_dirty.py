"""Tests for _porcelain_paths — the git-status path parser under working_dirty.

Regression: git() strips its stdout, chopping the leading status-column space off
the FIRST porcelain line, so " M BACKLOG.md" used to parse as "ACKLOG.md" and a
modified-but-excluded backlog falsely read as dirty at preflight. _porcelain_paths
parses RAW porcelain (status in cols 0-1, path from col 3), so the offset holds.
"""
import orchestrator as o


def test_modified_unstaged_first_line():
    # ' M file' — leading space + M; the offset-shift bug lived here.
    assert list(o._porcelain_paths(" M BACKLOG.md")) == ["BACKLOG.md"]


def test_staged_modified():
    # 'M  file' — staged, X='M' Y=' '.
    assert list(o._porcelain_paths("M  orchestrator.py")) == ["orchestrator.py"]


def test_untracked():
    assert list(o._porcelain_paths("?? new_file.py")) == ["new_file.py"]


def test_multiple_lines_keep_all_paths():
    text = " M BACKLOG.md\n?? scratch.py\nM  a/b.py"
    assert list(o._porcelain_paths(text)) == ["BACKLOG.md", "scratch.py", "a/b.py"]


def test_quoted_path_unquoted():
    assert list(o._porcelain_paths('?? "with space.py"')) == ["with space.py"]


def test_blank_and_empty_skipped():
    assert list(o._porcelain_paths("")) == []
    assert list(o._porcelain_paths("\n \n M x.py\n")) == ["x.py"]


def test_working_dirty_excludes_only_modified_backlog(tmp_path, monkeypatch):
    # End-to-end over the real helper: a lone modified BACKLOG.md that is excluded
    # must read clean (the bug reported it dirty).
    import subprocess

    def _run(cmd, **kw):
        return subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    monkeypatch.setattr(o, "run", _run)
    _run(["git", "init", "-q"])
    _run(["git", "config", "user.email", "t@t"])
    _run(["git", "config", "user.name", "t"])
    (tmp_path / "BACKLOG.md").write_text("- [ ] a\n", encoding="utf-8")
    _run(["git", "add", "-A"])
    _run(["git", "commit", "-qm", "init"])
    (tmp_path / "BACKLOG.md").write_text("- [ ] a\n- [ ] b\n", encoding="utf-8")

    assert o.working_dirty({"BACKLOG.md"}) is False   # excluded -> clean
    assert o.working_dirty(set()) is True             # not excluded -> dirty
