"""Tests for §8.6 non-codifiable-acceptance routing (orchestrator).

Two pure decisions:
  - is_codifiable_acceptance(criterion): True when the criterion names a test
    (acceptance_tokens non-empty) OR carries a runnable-command signal (a known
    runner/verb, a leading ./, a backtick-wrapped command, or an exit-0/returns-0/
    passes phrase); False for empty/None or purely subjective prose.
  - needs_human_checkpoint(task): True only when a task has a non-codifiable
    acceptance criterion (auto-mode routes it to a human checkpoint instead of
    guessing). False when the task has no acceptance or a codifiable one.
"""
import types

import orchestrator as o


# ---------------------------------------------------------------- is_codifiable_acceptance
def test_test_named_criterion_is_codifiable():
    # Names a test identifier -> acceptance_tokens is non-empty -> codifiable.
    assert o.is_codifiable_acceptance("test_widget_renders passes") is True
    assert o.is_codifiable_acceptance("tests/test_widget.py::test_renders is green") is True


def test_runnable_command_criterion_is_codifiable():
    # A runnable-command signal (runner/verb, ./, backtick cmd, exit/returns 0) is
    # codifiable even with no test identifier named.
    assert o.is_codifiable_acceptance("running `ruff check .` exits 0") is True
    assert o.is_codifiable_acceptance("npm run build succeeds") is True
    assert o.is_codifiable_acceptance("./scripts/verify.sh returns 0") is True
    assert o.is_codifiable_acceptance("the command `make lint` passes") is True


def test_subjective_prose_is_not_codifiable():
    # Purely subjective prose gives the harness no mechanical handle.
    assert o.is_codifiable_acceptance("the UI looks clean and modern") is False
    assert o.is_codifiable_acceptance("feels responsive and intuitive") is False


def test_empty_and_none_are_not_codifiable():
    assert o.is_codifiable_acceptance("") is False
    assert o.is_codifiable_acceptance("   ") is False
    assert o.is_codifiable_acceptance(None) is False


# ---------------------------------------------------------------- needs_human_checkpoint
def _task(acceptance):
    return types.SimpleNamespace(id="t", title="a task", acceptance=acceptance)


def test_needs_checkpoint_for_non_codifiable_acceptance():
    assert o.needs_human_checkpoint(_task("the UI looks clean")) is True


def test_no_checkpoint_for_codifiable_acceptance():
    assert o.needs_human_checkpoint(_task("test_renders passes")) is False
    assert o.needs_human_checkpoint(_task("`pytest -q` exits 0")) is False


def test_no_checkpoint_when_no_acceptance():
    # A task with no acceptance criterion (None, empty, or missing attr) is never routed.
    assert o.needs_human_checkpoint(_task(None)) is False
    assert o.needs_human_checkpoint(_task("")) is False
    assert o.needs_human_checkpoint(types.SimpleNamespace(id="t", title="a task")) is False
