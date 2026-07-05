"""Tests for the resume consecutive-failure reset (orchestrator.resumed_failure_count).

A run that halts at `max_consecutive_failures` persists that count in state.json.
Resuming would re-trip the halt check immediately unless the window is reset. The
pure helper hands back a fresh window (0) ONLY when a positive cap is set and the
persisted count has reached it; every other case (below cap, zero, or a disabled
None / 0 / negative cap) returns the count unchanged.
"""
import orchestrator as o


# ---------------------------------------------------------------- reset fires
def test_at_cap_resets_to_zero():
    assert o.resumed_failure_count(3, 3) == 0


def test_above_cap_resets_to_zero():
    assert o.resumed_failure_count(5, 3) == 0


# ---------------------------------------------------------------- no reset
def test_below_cap_unchanged():
    assert o.resumed_failure_count(2, 3) == 2


def test_zero_unchanged():
    assert o.resumed_failure_count(0, 3) == 0


# ---------------------------------------------------------------- disabled cap
def test_none_cap_unchanged():
    assert o.resumed_failure_count(5, None) == 5


def test_zero_cap_unchanged():
    assert o.resumed_failure_count(5, 0) == 5


def test_negative_cap_unchanged():
    assert o.resumed_failure_count(5, -1) == 5
