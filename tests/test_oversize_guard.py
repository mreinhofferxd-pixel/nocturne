"""Tests for the §8.7 mechanical oversize-guard.

is_oversize_diff(diff_text, threshold) counts the DISTINCT changed files in a
unified diff from its file headers (`diff --git` / `+++`), never the `+`/`-`
content lines, and returns True only when that count exceeds the threshold.
"""
import orchestrator


def _file_diff(path, added=1, removed=0):
    """A well-formed single-file unified-diff block with `added`/`removed`
    content lines (which must NEVER be mistaken for extra files)."""
    lines = [
        f"diff --git a/{path} b/{path}",
        "index 1111111..2222222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        "@@ -1,3 +1,3 @@",
    ]
    lines += [f"-old line {i}" for i in range(removed)]
    lines += [f"+new line {i}" for i in range(added)]
    return lines


def _multi_file_diff(n, added=1, removed=0):
    """A unified diff spanning `n` distinct files."""
    out = []
    for i in range(n):
        out += _file_diff(f"src/mod{i}.py", added=added, removed=removed)
    return "\n".join(out) + "\n"


# ---- under / at / over the threshold
def test_under_threshold_is_not_oversize():
    d = _multi_file_diff(3)
    assert orchestrator.is_oversize_diff(d, 25) is False


def test_at_threshold_is_not_oversize():
    # count == threshold: "exceeds" is strict, so at the line is NOT oversize.
    d = _multi_file_diff(5)
    assert orchestrator.is_oversize_diff(d, 5) is False


def test_over_threshold_is_oversize():
    d = _multi_file_diff(6)
    assert orchestrator.is_oversize_diff(d, 5) is True


def test_default_threshold_boundary():
    # The config default is 25: 25 files is fine, 26 tips over.
    assert orchestrator.is_oversize_diff(_multi_file_diff(25), 25) is False
    assert orchestrator.is_oversize_diff(_multi_file_diff(26), 25) is True


# ---- headers, not content, are counted
def test_content_lines_are_not_counted_as_files():
    # One file, but 100 added + 40 removed content lines. File count is 1, so a
    # low threshold must NOT trip -- content lines are never files.
    d = "\n".join(_file_diff("src/big.py", added=100, removed=40)) + "\n"
    assert orchestrator.is_oversize_diff(d, 5) is False
    assert orchestrator._changed_files(d) == {"src/big.py"}


def test_added_content_line_shaped_like_a_header_is_ignored():
    # A `+`-prefixed content line whose text merely mentions "diff --git" is code,
    # not a file header, and must not inflate the count.
    lines = _file_diff("src/mod.py", added=0)
    lines.append("+    log('diff --git a/x b/x')")
    d = "\n".join(lines) + "\n"
    assert orchestrator._changed_files(d) == {"src/mod.py"}
    assert orchestrator.is_oversize_diff(d, 1) is False


def test_distinct_files_counted_once_across_both_headers():
    # `diff --git` and `+++` name the same path; the set dedups to one file.
    d = "\n".join(_file_diff("src/mod.py")) + "\n"
    assert orchestrator._changed_files(d) == {"src/mod.py"}


# ---- degenerate inputs
def test_empty_diff_is_not_oversize():
    assert orchestrator.is_oversize_diff("", 25) is False


def test_none_diff_is_not_oversize():
    assert orchestrator.is_oversize_diff(None, 25) is False


# ---- reason sharpening (spec §8.7 block message)
def test_oversize_reason_overrides_bare_reason():
    d = _multi_file_diff(30)
    assert orchestrator._oversize_reason("gate never passed", d, 25) == (
        "likely too large — split needed"
    )


def test_oversize_reason_keeps_bare_reason_when_small():
    d = _multi_file_diff(2)
    assert orchestrator._oversize_reason("gate never passed", d, 25) == "gate never passed"
