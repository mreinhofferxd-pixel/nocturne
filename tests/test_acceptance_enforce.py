"""Tests for §8.6 acceptance-test ENFORCEMENT (orchestrator).

The parse-half (markdown_adapter.parse_acceptance -> task.acceptance) is covered
by test_acceptance_parse.py. Here we pin the enforcement half:
  - acceptance_tokens: mine a criterion for test_* names / .py paths (pure)
  - acceptance_in_diff: is any such token on an ADDED diff line (pure)
  - process_task rejects a green attempt whose diff pins no acceptance test, while a
    tokenless (advisory-only) or test-present attempt still succeeds.
"""
import types

import orchestrator as o


def _diff(path, added=(), removed=(), context=()):
    """Minimal well-formed unified diff (mirrors test_diff_guard's helper)."""
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


# ---------------------------------------------------------------- acceptance_tokens
def test_tokens_test_function_name():
    assert o.acceptance_tokens("test_widget_renders passes") == ["test_widget_renders"]


def test_tokens_node_id_yields_path_and_fn_names():
    toks = o.acceptance_tokens("tests/test_widget.py::test_renders is green")
    assert "tests/test_widget.py" in toks     # .py path
    assert "test_renders" in toks             # test_ function name
    # paths come before test-fn names, and the list is de-duplicated
    assert toks.index("tests/test_widget.py") < toks.index("test_renders")
    assert len(toks) == len(set(toks))


def test_tokens_py_path_boundary_excludes_pyc():
    # `.py\b` matches a real .py file but not a .pyc/.pyx suffix.
    assert o.acceptance_tokens("see foo.py and bar.pyc") == ["foo.py"]


def test_tokens_tokenless_criterion_is_empty():
    assert o.acceptance_tokens("widget renders correctly") == []


def test_tokens_empty_and_none():
    assert o.acceptance_tokens("") == []
    assert o.acceptance_tokens(None) == []


# ---------------------------------------------------------------- acceptance_in_diff
def test_in_diff_true_when_token_on_added_line():
    d = _diff("tests/test_widget.py", added=["def test_widget_renders():"])
    assert o.acceptance_in_diff(d, "test_widget_renders passes") is True


def test_in_diff_false_when_token_only_on_removed_line():
    d = _diff("tests/test_widget.py", removed=["def test_widget_renders():"])
    assert o.acceptance_in_diff(d, "test_widget_renders passes") is False


def test_in_diff_false_when_token_only_in_file_header():
    # The .py-path token appears only in the +++/--- headers, never a +content line.
    d = _diff("tests/test_widget.py", added=["    x = 1"])
    assert o.acceptance_in_diff(d, "tests/test_widget.py must exist") is False


def test_in_diff_false_for_tokenless_criterion():
    d = _diff("src/widget.py", added=["def render(): return 'ok'"])
    assert o.acceptance_in_diff(d, "widget renders") is False
    assert o.acceptance_in_diff(d, "") is False
    assert o.acceptance_in_diff(d, None) is False


# ---------------------------------------------------------------- process_task wiring
class _FakeAdapter:
    def __init__(self):
        self.marked = []

    def mark_done(self, task):
        self.marked.append(task)

    def list(self):
        return []


def _run(monkeypatch, acceptance, diff, gate_ok=True):
    """Drive process_task once (max_retries=1) with all IO stubbed: run_claude,
    git, run_gate, working_dirty and discard_inflight are patched so only the
    done-path decision logic executes. Returns (result_tuple, adapter)."""
    calls = {"head": 0}

    def fake_head():
        calls["head"] += 1
        return "AAA" if calls["head"] == 1 else "BBB"  # first call = `before`

    def fake_git(*args, **kw):
        return diff if args[:1] == ("diff",) else ""

    monkeypatch.setattr(o, "head_sha", fake_head)
    monkeypatch.setattr(o, "git", fake_git)
    monkeypatch.setattr(o, "run_claude", lambda *a, **k: o.ClaudeResult(0.0, False, None))
    monkeypatch.setattr(o, "run_gate", lambda gate: (gate_ok, "gate output"))
    monkeypatch.setattr(o, "working_dirty", lambda exclude: False)
    monkeypatch.setattr(o, "discard_inflight", lambda *a, **k: None)

    task = types.SimpleNamespace(title="build widget", id="task-1", acceptance=acceptance)
    cfg = {"gate": ["pytest"], "model": "m", "budget": {"max_retries": 1}}
    state = {"iterations": 0, "cost_usd": 0.0}
    adapter = _FakeAdapter()
    return o.process_task(task, cfg, adapter, state, "BACKLOG.md"), adapter


def test_green_but_missing_acceptance_test_is_rejected(monkeypatch):
    # Gate green, but the diff adds only production code -- no test pins the criterion.
    diff = _diff("src/widget.py", added=["def render():", "    return 'ok'"])
    (done, sha, reason), adapter = _run(monkeypatch, "test_widget_renders passes", diff)
    assert done is False
    assert sha is None
    assert "acceptance" in reason.lower()
    assert adapter.marked == []          # never marked done


def test_green_with_acceptance_test_is_accepted(monkeypatch):
    # Same criterion, but this diff adds the pinning test -> attempt succeeds.
    diff = _diff("tests/test_widget.py",
                 added=["def test_widget_renders():", "    assert render()"])
    (done, sha, reason), adapter = _run(monkeypatch, "test_widget_renders passes", diff)
    assert done is True
    assert len(adapter.marked) == 1


def test_green_with_tokenless_acceptance_is_accepted(monkeypatch):
    # A criterion naming no test token is advisory-only, never enforced.
    diff = _diff("src/widget.py", added=["def render(): return 'ok'"])
    (done, sha, reason), adapter = _run(monkeypatch, "widget renders nicely", diff)
    assert done is True
    assert len(adapter.marked) == 1


def test_green_without_acceptance_is_accepted(monkeypatch):
    # No acceptance criterion at all -> enforcement is bypassed entirely.
    diff = _diff("src/widget.py", added=["def render(): return 'ok'"])
    (done, sha, reason), adapter = _run(monkeypatch, None, diff)
    assert done is True
    assert len(adapter.marked) == 1
