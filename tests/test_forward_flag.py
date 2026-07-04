"""Tests for the §8.7 forward-flag scope-drift backstop.

Covers the two pure transforms and their surfacing in the prompt:
  - parse_forward_flags: pull `LOOP-FLAG: <what changed>` lines a just-finished
    agent left in its commit body.
  - format_flag_notice: render pending flags as a lean prompt heads-up (empty when
    there are none -> zero prompt cost).
  - build_prompt: always teaches the LOOP-FLAG convention, and surfaces incoming
    flags to the next task without disturbing the prior-attempt feedback.
"""
import types

import orchestrator


def _task(title="Add the widget", tid="t1"):
    return types.SimpleNamespace(title=title, id=tid)


# ---- parse_forward_flags (pure)
def test_parse_single_flag_from_commit_body():
    body = "feat: reshape user model\n\nLOOP-FLAG: changed the User model shape\n"
    assert orchestrator.parse_forward_flags(body) == ["changed the User model shape"]


def test_parse_multiple_flags():
    body = (
        "refactor: api\n\n"
        "LOOP-FLAG: renamed /users to /accounts\n"
        "LOOP-FLAG: dropped the legacy id field\n"
    )
    assert orchestrator.parse_forward_flags(body) == [
        "renamed /users to /accounts",
        "dropped the legacy id field",
    ]


def test_parse_is_case_insensitive_and_trims():
    body = "x\n\n  loop-flag:   trailing space trimmed   "
    assert orchestrator.parse_forward_flags(body) == ["trailing space trimmed"]


def test_parse_ignores_empty_flag_text():
    body = "x\n\nLOOP-FLAG:   \nLOOP-FLAG: real one"
    assert orchestrator.parse_forward_flags(body) == ["real one"]


def test_parse_no_marker_is_empty():
    assert orchestrator.parse_forward_flags("just a normal commit message") == []


def test_parse_empty_and_none_are_empty():
    assert orchestrator.parse_forward_flags("") == []
    assert orchestrator.parse_forward_flags(None) == []


# ---- format_flag_notice (pure)
def test_notice_empty_when_no_flags():
    assert orchestrator.format_flag_notice([]) == ""
    assert orchestrator.format_flag_notice(None) == ""


def test_notice_drops_blank_entries():
    assert orchestrator.format_flag_notice(["   ", ""]) == ""


def test_notice_lists_each_flag():
    out = orchestrator.format_flag_notice(["User shape changed", "route renamed"])
    assert "Heads-up from earlier tasks" in out
    assert "- User shape changed" in out
    assert "- route renamed" in out


# ---- build_prompt surfacing
def test_prompt_always_teaches_the_convention():
    p = orchestrator.build_prompt(_task(), ["ruff check ."], None)
    assert "LOOP-FLAG: <what changed>" in p


def test_prompt_without_flags_has_no_heads_up():
    p = orchestrator.build_prompt(_task(), ["ruff check ."], None)
    assert "Heads-up from earlier tasks" not in p


def test_prompt_surfaces_incoming_flags():
    p = orchestrator.build_prompt(
        _task(), ["ruff check ."], None, flags=["changed the User model shape"]
    )
    assert "Heads-up from earlier tasks" in p
    assert "- changed the User model shape" in p


def test_prompt_keeps_prior_feedback_after_notice():
    p = orchestrator.build_prompt(
        _task(), ["ruff check ."], "AssertionError: boom", flags=["route renamed"]
    )
    # both the heads-up and the prior-attempt diagnosis are present, in order
    assert p.index("Heads-up from earlier tasks") < p.index("previous attempt failed")
    assert "AssertionError: boom" in p


def test_flags_roundtrip_parse_to_notice():
    # a harvested commit body flows through parse -> notice unchanged
    flags = orchestrator.parse_forward_flags("c\n\nLOOP-FLAG: db schema migrated")
    assert "- db schema migrated" in orchestrator.format_flag_notice(flags)
