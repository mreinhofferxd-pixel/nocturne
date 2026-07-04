"""Tests for the markdown backlog adapter."""
from markdown_adapter import MarkdownBacklog


def _backlog(tmp_path, body):
    p = tmp_path / "BACKLOG.md"
    p.write_text(body, encoding="utf-8")
    return MarkdownBacklog(str(p))


SAMPLE = """# Backlog

- [ ] first task
- [x] already done
- [ ] second task
"""


def test_list_parses_all_checkboxes(tmp_path):
    b = _backlog(tmp_path, SAMPLE)
    tasks = b.list()
    assert [t.title for t in tasks] == ["first task", "already done", "second task"]
    assert [t.done for t in tasks] == [False, True, False]
    assert [t.id for t in tasks] == ["task-1", "task-2", "task-3"]


def test_next_task_returns_first_unchecked(tmp_path):
    b = _backlog(tmp_path, SAMPLE)
    nxt = b.next_task()
    assert nxt is not None
    assert nxt.title == "first task"


def test_mark_done_checks_the_box(tmp_path):
    b = _backlog(tmp_path, SAMPLE)
    first = b.next_task()
    b.mark_done(first)
    # after marking, next todo advances to the later unchecked task
    assert b.next_task().title == "second task"
    assert b.get("task-1").done is True


def test_next_task_none_when_all_done(tmp_path):
    b = _backlog(tmp_path, "- [x] a\n- [x] b\n")
    assert b.next_task() is None
