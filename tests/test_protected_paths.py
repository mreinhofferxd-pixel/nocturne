"""Tests for the §9 protected-paths post-commit guard (orchestrator).

touches_protected(diff_text, patterns) reads a unified diff's file HEADERS only
(via _changed_files, never the `+`/`-` content) and returns True when any changed
path matches any glob in `patterns`. A pattern ending in `/**` is a recursive
prefix (the prefix dir itself or anything under it); every other pattern uses
fnmatch glob semantics. Empty patterns never matches.

The done-path wiring rejects an otherwise-green attempt whose committed diff
touches a protected path -- mirroring the suppressing / acceptance rejections.
"""
import types

import orchestrator as o


def _diff(*paths, added=("x = 1",)):
    """A well-formed unified diff spanning the given file paths. The `+content`
    lines must never be miscounted as protected paths -- only the headers are read."""
    out = []
    for path in paths:
        out += [
            f"diff --git a/{path} b/{path}",
            "index 1111111..2222222 100644",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -0,0 +1,1 @@",
        ]
        out += [f"+{a}" for a in added]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- plain glob
def test_plain_glob_matches_dotenv():
    d = _diff(".env")
    assert o.touches_protected(d, [".env*"]) is True


def test_plain_glob_matches_dotenv_suffixed():
    d = _diff(".env.production")
    assert o.touches_protected(d, [".env*"]) is True


def test_plain_glob_does_not_match_unrelated():
    d = _diff("src/app.py")
    assert o.touches_protected(d, [".env*"]) is False


# ---------------------------------------------------------------- recursive prefix
def test_recursive_prefix_matches_nested_file():
    d = _diff("secrets/prod/key.pem")
    assert o.touches_protected(d, ["secrets/**"]) is True


def test_recursive_prefix_matches_direct_child():
    d = _diff("secrets/token")
    assert o.touches_protected(d, ["secrets/**"]) is True


def test_recursive_prefix_matches_prefix_dir_itself():
    # A path equal to the prefix (the dir itself, no trailing slash) is protected.
    d = _diff("secrets")
    assert o.touches_protected(d, ["secrets/**"]) is True


def test_recursive_prefix_does_not_match_sibling_prefix():
    # `secretsX` shares the text prefix but is NOT under `secrets/`.
    d = _diff("secretsX/key")
    assert o.touches_protected(d, ["secrets/**"]) is False


# ---------------------------------------------------------------- clearly non-matching
def test_non_matching_diff():
    d = _diff("src/app.py", "docs/readme.md")
    assert o.touches_protected(d, [".env*", "secrets/**", "ci/*.yml"]) is False


def test_content_line_shaped_like_protected_path_is_ignored():
    # A `+`-content line naming .env is code, not a changed file -> not protected.
    d = _diff("src/app.py", added=["load('.env')"])
    assert o.touches_protected(d, [".env*"]) is False


# ---------------------------------------------------------------- empty patterns
def test_empty_patterns_never_matches():
    d = _diff(".env", "secrets/key")
    assert o.touches_protected(d, []) is False


def test_none_patterns_never_matches():
    d = _diff(".env")
    assert o.touches_protected(d, None) is False


# ---------------------------------------------------------------- degenerate diffs
def test_empty_diff_is_not_protected():
    assert o.touches_protected("", [".env*"]) is False
    assert o.touches_protected(None, [".env*"]) is False


# ---------------------------------------------------------------- process_task wiring
class _FakeAdapter:
    def __init__(self):
        self.marked = []

    def mark_done(self, task):
        self.marked.append(task)

    def list(self):
        return []


def _run(monkeypatch, diff, patterns):
    """Drive process_task once (max_retries=1) with all IO stubbed so only the
    done-path decision executes. Mirrors test_acceptance_enforce's harness."""
    calls = {"head": 0}

    def fake_head():
        calls["head"] += 1
        return "AAA" if calls["head"] == 1 else "BBB"  # first call = `before`

    def fake_git(*args, **kw):
        return diff if args[:1] == ("diff",) else ""

    monkeypatch.setattr(o, "head_sha", fake_head)
    monkeypatch.setattr(o, "git", fake_git)
    monkeypatch.setattr(o, "run_claude", lambda *a, **k: o.ClaudeResult(0.0, False, None))
    monkeypatch.setattr(o, "run_gate", lambda gate: (True, "gate output"))
    monkeypatch.setattr(o, "working_dirty", lambda exclude: False)
    monkeypatch.setattr(o, "discard_inflight", lambda *a, **k: None)

    task = types.SimpleNamespace(title="wire config", id="task-1", acceptance=None)
    cfg = {
        "gate": ["pytest"], "model": "m", "budget": {"max_retries": 1},
        "guardrails": {"protected_paths": patterns},
    }
    state = {"iterations": 0, "cost_usd": 0.0}
    adapter = _FakeAdapter()
    return o.process_task(task, cfg, adapter, state, "BACKLOG.md"), adapter


def test_green_touching_protected_path_is_rejected(monkeypatch):
    diff = _diff("secrets/prod.key", added=["TOKEN=abc"])
    (done, sha, reason), adapter = _run(monkeypatch, diff, ["secrets/**"])
    assert done is False
    assert sha is None
    assert "protected" in reason.lower()
    assert adapter.marked == []          # never marked done


def test_green_outside_protected_paths_is_accepted(monkeypatch):
    diff = _diff("src/config.py", added=["DEBUG = False"])
    (done, sha, reason), adapter = _run(monkeypatch, diff, ["secrets/**", ".env*"])
    assert done is True
    assert len(adapter.marked) == 1
