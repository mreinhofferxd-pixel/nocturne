"""Tests for the section 9 checkpoint modes (orchestrator.should_checkpoint).

should_checkpoint(mode, current_task, next_task) is the pure decision behind the
`mode` config: "auto" (default) never pauses; "checkpoint-task" pauses after every
completed task (but not when the backlog is exhausted); "checkpoint-unit" pauses only
at a unit boundary -- the next task belongs to a different ## heading group (8.3).
"""
import types

import orchestrator as o


def _task(unit=""):
    return types.SimpleNamespace(id="t", title="a task", unit=unit)


# ---------------------------------------------------------------- auto (never pauses)
def test_auto_never_checkpoints_with_next():
    assert o.should_checkpoint("auto", _task("A"), _task("B")) is False


def test_auto_never_checkpoints_across_unit_boundary():
    # Even a unit boundary does not pause under auto.
    assert o.should_checkpoint("auto", _task("Setup"), _task("Features")) is False


def test_auto_never_checkpoints_when_backlog_empty():
    assert o.should_checkpoint("auto", _task("A"), None) is False


# ---------------------------------------------------------------- checkpoint-task
def test_checkpoint_task_pauses_after_every_task():
    assert o.should_checkpoint("checkpoint-task", _task("A"), _task("A")) is True


def test_checkpoint_task_pauses_across_units_too():
    assert o.should_checkpoint("checkpoint-task", _task("A"), _task("B")) is True


def test_checkpoint_task_does_not_pause_when_next_is_none():
    # Nothing left to pause before -> no checkpoint (loop halts on "backlog empty").
    assert o.should_checkpoint("checkpoint-task", _task("A"), None) is False


# ---------------------------------------------------------------- checkpoint-unit
def test_checkpoint_unit_pauses_across_a_unit_boundary():
    assert o.should_checkpoint("checkpoint-unit", _task("Setup"), _task("Features")) is True


def test_checkpoint_unit_does_not_pause_within_a_unit():
    assert o.should_checkpoint("checkpoint-unit", _task("Setup"), _task("Setup")) is False


def test_checkpoint_unit_does_not_pause_when_next_is_none():
    assert o.should_checkpoint("checkpoint-unit", _task("Setup"), None) is False


def test_checkpoint_unit_treats_missing_unit_attr_as_empty():
    # A task with no `unit` attribute reads as "" -- two such tasks share the default
    # unit, so no boundary; one tagged vs one bare IS a boundary.
    bare = types.SimpleNamespace(id="t", title="x")
    assert o.should_checkpoint("checkpoint-unit", bare, types.SimpleNamespace(id="u", title="y")) is False
    assert o.should_checkpoint("checkpoint-unit", bare, _task("Features")) is True


# ---------------------------------------------------------------- unknown mode
def test_unknown_mode_degrades_to_auto():
    assert o.should_checkpoint("bogus", _task("A"), _task("B")) is False
