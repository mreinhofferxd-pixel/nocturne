"""Tests for §8.6 acceptance-criterion parsing and prompt surfacing.

parse_acceptance pulls an optional @acceptance(<criterion>) marker out of a
backlog title; build_prompt surfaces the criterion as a hard rule when the
task carries one. Harness enforcement of the criterion is a later task.
"""
import types

import orchestrator
from markdown_adapter import MarkdownBacklog, parse_acceptance


# ---- parse_acceptance (pure)
def test_marker_present():
    clean, acc = parse_acceptance("build the widget @acceptance(widget renders)")
    assert clean == "build the widget"
    assert acc == "widget renders"


def test_marker_absent():
    clean, acc = parse_acceptance("build the widget")
    assert clean == "build the widget"
    assert acc is None


def test_marker_alongside_trailing_tier_tag():
    clean, acc = parse_acceptance("build widget @acceptance(must render) [complex]")
    assert clean == "build widget [complex]"
    assert acc == "must render"
    assert orchestrator.parse_tier(clean) == "complex"


def test_whitespace_collapse():
    clean, acc = parse_acceptance("build   the @acceptance(x)   widget")
    assert clean == "build the widget"
    assert acc == "x"


# ---- adapter populates the field
def test_adapter_populates_acceptance(tmp_path):
    p = tmp_path / "BACKLOG.md"
    p.write_text(
        "- [ ] ship it @acceptance(gate green) [simple]\n- [ ] plain task\n",
        encoding="utf-8",
    )
    tasks = MarkdownBacklog(str(p)).list()
    assert tasks[0].title == "ship it [simple]"
    assert tasks[0].acceptance == "gate green"
    assert tasks[1].acceptance is None


# ---- build_prompt surfacing
def test_build_prompt_surfaces_acceptance():
    task = types.SimpleNamespace(
        title="do thing", id="t1", acceptance="all API calls are retried"
    )
    p = orchestrator.build_prompt(task, ["pytest"], None)
    assert "all API calls are retried" in p
    assert "acceptance" in p.lower()
    assert "test" in p.lower()


def test_build_prompt_tolerates_task_without_acceptance_attr():
    task = types.SimpleNamespace(title="bare task", id="t1")
    p = orchestrator.build_prompt(task, ["pytest"], None)
    assert "Hard rule" not in p
