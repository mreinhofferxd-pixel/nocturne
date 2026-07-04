"""Tests for §8.3 unit grouping in the markdown adapter."""
from markdown_adapter import MarkdownBacklog, parse_units


def _backlog(tmp_path, body):
    p = tmp_path / "BACKLOG.md"
    p.write_text(body, encoding="utf-8")
    return MarkdownBacklog(str(p))


GROUPED = """# Backlog

## Setup
- [ ] init repo
- [x] add ci

## Features
- [ ] feature a
- [ ] feature b
"""


def test_tasks_grouped_under_headings(tmp_path):
    b = _backlog(tmp_path, GROUPED)
    assert b.units() == [("Setup", [0, 1]), ("Features", [2, 3])]


def test_pre_heading_tasks_in_default_unit(tmp_path):
    body = "# Backlog\n\n- [ ] loose one\n\n## Setup\n- [ ] init\n"
    b = _backlog(tmp_path, body)
    assert b.units() == [("", [0]), ("Setup", [1])]


def test_heading_without_checkboxes_omitted(tmp_path):
    body = "## Prose\n\nno tasks here, only words\n\n## Real\n- [ ] do it\n"
    b = _backlog(tmp_path, body)
    assert b.units() == [("Real", [0])]


def test_task_unit_field_populated(tmp_path):
    b = _backlog(tmp_path, GROUPED)
    tasks = b.list()
    assert [t.unit for t in tasks] == ["Setup", "Setup", "Features", "Features"]


def test_parse_units_is_pure_and_matches_task_index(tmp_path):
    lines = ["## A\n", "- [ ] x\n", "## B\n", "- [x] y\n"]
    assert parse_units(lines) == [("A", [0]), ("B", [1])]
