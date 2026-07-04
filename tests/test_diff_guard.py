"""Tests for the anti-gaming diff-guard (spec §8.5).

is_suppressing_diff flags a diff that ADDS a skip/xfail/@ts-ignore/# type: ignore/
# noqa/eslint-disable marker or NETS a removed assertion. modifies_tests detects
the per-task opt-out tag that relaxes the guard.
"""
import orchestrator


def _diff(path, added=(), removed=(), context=()):
    """Build a minimal but well-formed unified diff. `context` lines carry the
    leading space; added/removed carry +/-. File headers use +++/---."""
    lines = [
        f"diff --git a/{path} b/{path}",
        "index 1111111..2222222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        "@@ -1,3 +1,3 @@",
    ]
    lines += [f" {c}" for c in context]
    lines += [f"-{r}" for r in removed]
    lines += [f"+{a}" for a in added]
    return "\n".join(lines) + "\n"


# ---- honest diffs are not flagged
def test_empty_diff_is_not_suppressing():
    assert orchestrator.is_suppressing_diff("") is False


def test_none_diff_is_not_suppressing():
    assert orchestrator.is_suppressing_diff(None) is False


def test_plain_feature_diff_is_not_suppressing():
    d = _diff("src/calc.py", added=["def add(a, b):", "    return a + b"])
    assert orchestrator.is_suppressing_diff(d) is False


def test_added_assertion_is_not_suppressing():
    d = _diff("tests/test_calc.py", added=["    assert add(1, 2) == 3"])
    assert orchestrator.is_suppressing_diff(d) is False


# ---- added suppression markers are flagged
def test_added_pytest_skip_marker():
    d = _diff("tests/test_calc.py", added=["@pytest.mark.skip('flaky')",
                                           "def test_add():"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_pytest_skipif_marker():
    d = _diff("tests/test_calc.py", added=["@pytest.mark.skipif(True, reason='x')"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_pytest_skip_call():
    d = _diff("tests/test_calc.py", added=["    pytest.skip('not ready')"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_xfail_marker():
    d = _diff("tests/test_calc.py", added=["@pytest.mark.xfail"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_jest_it_skip():
    d = _diff("src/calc.test.js", added=["  it.skip('adds', () => {"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_xit_marker():
    d = _diff("src/calc.test.js", added=["  xit('adds', () => {"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_ts_ignore():
    d = _diff("src/calc.ts", added=["  // @ts-ignore", "  foo.bar()"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_type_ignore():
    d = _diff("src/calc.py", added=["    x = untyped()  # type: ignore"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_noqa():
    d = _diff("src/calc.py", added=["import os  # noqa"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_added_eslint_disable():
    d = _diff("src/calc.js", added=["  // eslint-disable-next-line no-unused-vars",
                                    "  const x = 1;"])
    assert orchestrator.is_suppressing_diff(d) is True


# ---- removed assertions are flagged
def test_removed_python_assert():
    d = _diff("tests/test_calc.py",
              context=["def test_add():"], removed=["    assert add(1, 2) == 3"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_removed_unittest_assert():
    d = _diff("tests/test_calc.py", removed=["        self.assertEqual(add(1, 2), 3)"])
    assert orchestrator.is_suppressing_diff(d) is True


def test_removed_jest_expect():
    d = _diff("src/calc.test.js", removed=["    expect(add(1, 2)).toBe(3);"])
    assert orchestrator.is_suppressing_diff(d) is True


# ---- net logic: an in-place edit is not suppression
def test_edited_assertion_value_is_not_suppressing():
    # One assert removed, one added -> net zero -> honest edit, not a deletion.
    d = _diff("tests/test_calc.py",
              removed=["    assert add(1, 2) == 4"],
              added=["    assert add(1, 2) == 3"])
    assert orchestrator.is_suppressing_diff(d) is False


def test_removing_a_noqa_is_not_suppressing():
    # Deleting a suppression marker un-suppresses; must not be flagged.
    d = _diff("src/calc.py", removed=["import os  # noqa"], added=["import os"])
    assert orchestrator.is_suppressing_diff(d) is False


# ---- headers and context never count as changes
def test_skip_in_filename_header_is_ignored():
    # The path contains "skip" but only appears in the +++/--- headers.
    d = _diff("tests/test_skiplist.py", added=["    assert len(sl) == 3"])
    assert orchestrator.is_suppressing_diff(d) is False


def test_skip_in_context_line_is_ignored():
    # A skip marker on an unchanged (context) line is pre-existing, not added.
    d = _diff("tests/test_calc.py",
              context=["@pytest.mark.skip('old')"],
              added=["    y = 2"])
    assert orchestrator.is_suppressing_diff(d) is False


# ---- a suppressed test still trips even when honest lines are added
def test_skip_wins_over_added_code():
    d = _diff("tests/test_calc.py",
              added=["@pytest.mark.skip", "def test_add():", "    assert add(1, 1) == 2"])
    assert orchestrator.is_suppressing_diff(d) is True


# ---- modifies_tests tag detection
def test_modifies_tests_tag_present():
    assert orchestrator.modifies_tests("rework flaky suite [modifies-tests]") is True


def test_refactor_tests_tag_present():
    assert orchestrator.modifies_tests("split test helpers [refactor-tests]") is True


def test_modifies_tests_tag_case_insensitive():
    assert orchestrator.modifies_tests("thing [Modifies-Tests]") is True


def test_modifies_tests_absent():
    assert orchestrator.modifies_tests("add subtract function") is False
