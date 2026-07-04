"""Tests for the §9 wall-clock budget cap (orchestrator.over_wallclock pure helper).

The cap is a hard ceiling on elapsed run time, enforced ONLY at the task boundary
(never mid-task, per the atomicity invariant). These pin the threshold arithmetic:
the under / at / over cases, the disabled (None / 0 / negative) cases that make the
guard opt-in, and the missing-start case (older state predating started_epoch)
which degrades to no-cap so a resume is never wrongly halted.
"""
import orchestrator as o

START = 1_000_000  # arbitrary fixed epoch; the helper only cares about the delta


# ---------------------------------------------------------------- active cap
def test_under_cap_is_false():
    # 9 minutes elapsed, 10-minute cap -> not yet over.
    assert o.over_wallclock(START, START + 9 * 60, 10) is False


def test_at_cap_is_true():
    # Reaching the cap exactly halts (>=), not strictly over.
    assert o.over_wallclock(START, START + 10 * 60, 10) is True


def test_over_cap_is_true():
    assert o.over_wallclock(START, START + 11 * 60, 10) is True


# ---------------------------------------------------------------- disabled cap
def test_none_cap_disables_guard():
    assert o.over_wallclock(START, START + 10_000 * 60, None) is False


def test_zero_cap_disables_guard():
    assert o.over_wallclock(START, START + 10_000 * 60, 0) is False


def test_negative_cap_disables_guard():
    assert o.over_wallclock(START, START + 10_000 * 60, -5) is False


# ---------------------------------------------------------------- missing start
def test_missing_started_epoch_disables_guard():
    # Older state without started_epoch -> state.get returns None -> no cap.
    assert o.over_wallclock(None, START + 10 * 60, 10) is False


def test_zero_started_epoch_disables_guard():
    # A falsy 0 start is treated as missing (no cap), never as epoch 0.
    assert o.over_wallclock(0, 10 * 60, 10) is False
