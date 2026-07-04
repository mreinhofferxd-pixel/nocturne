"""Baseline-green preflight (dogfood #6): a red gate BEFORE any task halts the
run up front instead of mislabeling pre-existing failures as task failures."""
from orchestrator import baseline_halt_reason


def test_red_baseline_returns_halt_message():
    msg = baseline_halt_reason(False, "$ pytest -q\n2 failed, 5 passed", True)
    assert msg is not None
    assert "baseline gate is RED" in msg
    assert "2 failed, 5 passed" in msg      # tail excerpt surfaces the failure
    assert "require_green_baseline" in msg  # names the opt-out


def test_green_baseline_returns_none():
    assert baseline_halt_reason(True, "all checks passed", True) is None


def test_red_baseline_opt_out_returns_none():
    assert baseline_halt_reason(False, "boom", False) is None


def test_green_baseline_opt_out_returns_none():
    assert baseline_halt_reason(True, "fine", False) is None


def test_long_tail_is_excerpted_from_the_end():
    tail = "x" * 5000 + "FINAL ERROR"
    msg = baseline_halt_reason(False, tail, True)
    assert msg is not None
    assert "FINAL ERROR" in msg    # the end of the tail survives
    assert len(msg) < 700          # the 5000-char head does not


def test_none_tail_is_safe():
    msg = baseline_halt_reason(False, None, True)
    assert msg is not None
    assert "baseline gate is RED" in msg
