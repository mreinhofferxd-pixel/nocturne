"""Tests for the stuck-detection helper (spec §8.1)."""
import orchestrator


def test_first_attempt_never_stuck():
    # No previous diff to compare against -> first attempt can't be stuck.
    assert orchestrator.no_progress(None, "diff --git a/x b/x\n+new\n") is False


def test_identical_diff_is_stuck():
    d = "diff --git a/x b/x\n-old\n+new\n"
    assert orchestrator.no_progress(d, d) is True


def test_different_diff_is_progress():
    assert orchestrator.no_progress("diff-A", "diff-B") is False


def test_two_empty_diffs_are_stuck():
    # Model produced nothing two attempts running -> stuck.
    assert orchestrator.no_progress("", "") is True


def test_empty_after_nonempty_is_progress():
    assert orchestrator.no_progress("something changed", "") is False
