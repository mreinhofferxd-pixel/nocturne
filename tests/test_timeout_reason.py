"""Per-task watchdog timeouts surface as an actionable retry message.

A timeout kill used to reach process_task's no-commit branch as the generic
"No commit was produced", hiding the real cause. timeout_prior turns a fired
watchdog into a message naming the cap and how to raise it; ClaudeResult grows
a timed_out field with a back-compatible default.
"""
from orchestrator import ClaudeResult, timeout_prior


def test_timeout_prior_names_seconds_and_config_key():
    msg = timeout_prior(True, 1800)
    assert msg is not None
    assert "1800" in msg
    assert "budget.max_seconds_per_task" in msg


def test_timeout_prior_none_when_not_timed_out():
    assert timeout_prior(False, 1800) is None


def test_claude_result_three_arg_back_compat():
    r = ClaudeResult(0.0, False, None)
    assert r.timed_out is False
