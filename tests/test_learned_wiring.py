"""Tests for the §16 learned.md CALL-SITE wiring (the writer itself is covered by
test_learned.py). Two pieces:

  - learned_from_failure / _capture_learned: the pure capture heuristic that mines
    a gate-failure tail on a gate-failure -> green recovery, deciding WHICH text (if
    any) becomes a learned bullet. Narrow by design: only reusable, repo-environmental
    frictions (missing module/tool, unrecognized command) are captured; one-off task
    bugs (assertion/lint failures) are not.
  - _learned_flag: builds the --append-system-prompt-file injection fragment, only
    when learned.md exists and is non-blank.
"""
import orchestrator


# ---- learned_from_failure: recognized reusable frictions become a hint
def test_learn_python_missing_module():
    tail = "$ python -m pytest -q\nModuleNotFoundError: No module named 'pytest'\n"
    assert orchestrator.learned_from_failure(tail) == (
        "python module `pytest` is required -- ensure it is installed/declared before use"
    )


def test_learn_python_dotted_module():
    tail = "ModuleNotFoundError: No module named 'foo.bar'"
    assert "`foo.bar`" in orchestrator.learned_from_failure(tail)


def test_learn_node_missing_module():
    tail = "Error: Cannot find module 'lodash'\n    at Function._resolve"
    assert orchestrator.learned_from_failure(tail) == (
        "node module `lodash` is required -- ensure it is installed before use"
    )


def test_learn_command_not_found():
    tail = "bash: line 1: pnpm: command not found\n"
    assert orchestrator.learned_from_failure(tail) == (
        "`pnpm` is not on PATH -- install it or invoke the correct command"
    )


def test_learn_powershell_not_recognized():
    tail = "The term 'ruff' is not recognized as the name of a cmdlet, function, ..."
    assert orchestrator.learned_from_failure(tail) == (
        "`ruff` is not recognized here -- install it or use the correct command"
    )


# ---- learned_from_failure: one-off task bugs are NOT conventions -> None
def test_assertion_failure_is_not_learned():
    tail = "$ python -m pytest -q\nE   AssertionError: assert 3 == 4\n1 failed"
    assert orchestrator.learned_from_failure(tail) is None


def test_lint_failure_is_not_learned():
    tail = "app.py:12:1: F401 'os' imported but unused\nFound 1 error."
    assert orchestrator.learned_from_failure(tail) is None


def test_empty_and_none_tail_learn_nothing():
    assert orchestrator.learned_from_failure("") is None
    assert orchestrator.learned_from_failure(None) is None


def test_first_matching_signal_wins_for_determinism():
    # Tail carries BOTH a missing-module and a command-not-found signal; the module
    # signal is earlier in _LEARN_SIGNALS, so it is the one returned.
    tail = (
        "make: node: command not found\n"
        "ModuleNotFoundError: No module named 'click'\n"
    )
    assert orchestrator.learned_from_failure(tail) == (
        "python module `click` is required -- ensure it is installed/declared before use"
    )


# ---- _capture_learned: only writes on a genuine, reusable recovery
def test_capture_none_tail_writes_nothing(tmp_path):
    f = tmp_path / "learned.md"
    assert orchestrator._capture_learned(None, path=str(f)) is None
    assert not f.exists()          # no prior gate failure -> file never created


def test_capture_unreusable_tail_writes_nothing(tmp_path):
    f = tmp_path / "learned.md"
    tail = "E   AssertionError: assert 1 == 2"
    assert orchestrator._capture_learned(tail, path=str(f)) is None
    assert not f.exists()


def test_capture_writes_normalized_bullet(tmp_path):
    f = tmp_path / "learned.md"
    tail = "ModuleNotFoundError: No module named 'httpx'"
    orchestrator._capture_learned(tail, path=str(f))
    body = f.read_text(encoding="utf-8")
    # append_learned adds the "- " marker and a trailing newline
    assert body == (
        "- python module `httpx` is required -- ensure it is installed/declared before use\n"
    )


def test_capture_is_deduped_across_calls(tmp_path):
    f = tmp_path / "learned.md"
    tail = "ModuleNotFoundError: No module named 'httpx'"
    orchestrator._capture_learned(tail, path=str(f))
    orchestrator._capture_learned(tail, path=str(f))   # same friction again
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1                              # dedupe_bounded collapses it


# ---- _learned_flag: inject only a non-empty learned.md
def test_flag_absent_file_is_empty(tmp_path):
    assert orchestrator._learned_flag(str(tmp_path / "learned.md")) == ""


def test_flag_blank_file_is_empty(tmp_path):
    f = tmp_path / "learned.md"
    f.write_text("\n   \n", encoding="utf-8")
    assert orchestrator._learned_flag(str(f)) == ""


def test_flag_nonempty_file_injects_path(tmp_path):
    f = tmp_path / "learned.md"
    f.write_text("- use pnpm\n", encoding="utf-8")
    flag = orchestrator._learned_flag(str(f))
    assert flag.startswith(" --append-system-prompt-file ")
    assert str(f) in flag
    assert flag.count('"') == 2                         # path is quoted (may contain spaces)
