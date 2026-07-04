"""Tests for the §9 dollar budget cap (orchestrator.over_budget pure helper).

The cap is a hard ceiling on cumulative best-effort cost, enforced ONLY at the
task boundary (never mid-task, per the atomicity invariant). These pin the
threshold arithmetic: the under / at / over cases plus the disabled (None / 0 /
negative) cases that make the guard opt-in.
"""
import orchestrator as o


# ---------------------------------------------------------------- active cap
def test_under_cap_is_false():
    assert o.over_budget(4.99, 5.0) is False


def test_at_cap_is_true():
    # Reaching the cap exactly halts (>=), not strictly over.
    assert o.over_budget(5.0, 5.0) is True


def test_over_cap_is_true():
    assert o.over_budget(6.0, 5.0) is True


def test_zero_spend_under_positive_cap_is_false():
    assert o.over_budget(0.0, 5.0) is False


# ---------------------------------------------------------------- disabled cap
def test_none_cap_disables_guard():
    # No cap configured -> never over budget, however much was spent.
    assert o.over_budget(1000.0, None) is False


def test_zero_cap_disables_guard():
    assert o.over_budget(1000.0, 0) is False


def test_negative_cap_disables_guard():
    assert o.over_budget(1000.0, -1) is False
