"""Tests for the §16 rolling learned-conventions writer.

Covers the two pure transforms behind `.loop/learned.md`:
  - format_learned_bullet: one `- `-prefixed, whitespace-collapsed line
  - dedupe_bounded: drops exact-duplicate bullets keeping the most-recent
    occurrence, then caps to the last `limit`
Plus a round-trip through the append_learned IO wrapper.
"""
import orchestrator


# ---- format_learned_bullet (pure)
def test_format_prefixes_and_collapses_whitespace():
    assert orchestrator.format_learned_bullet("use   pnpm") == "- use pnpm"


def test_format_collapses_newlines_and_tabs():
    assert orchestrator.format_learned_bullet("lint needs\t--max-warnings\n0") == (
        "- lint needs --max-warnings 0"
    )


def test_format_strips_surrounding_whitespace():
    assert orchestrator.format_learned_bullet("   tests in __tests__  ") == (
        "- tests in __tests__"
    )


def test_format_is_idempotent_on_existing_marker():
    once = orchestrator.format_learned_bullet("use pnpm")
    assert once == "- use pnpm"
    assert orchestrator.format_learned_bullet(once) == once


def test_format_strips_star_marker():
    assert orchestrator.format_learned_bullet("* use pnpm") == "- use pnpm"


# ---- dedupe_bounded: dedup keeps the LATEST occurrence
def test_dedup_keeps_most_recent_occurrence():
    # A appears at index 0 and 2; its latest position (2) is where it survives.
    assert orchestrator.dedupe_bounded(["- A", "- B", "- A", "- C"]) == [
        "- B", "- A", "- C",
    ]


def test_dedup_no_duplicates_preserves_order():
    bullets = ["- A", "- B", "- C"]
    assert orchestrator.dedupe_bounded(bullets) == bullets


def test_dedup_all_identical_collapses_to_one():
    assert orchestrator.dedupe_bounded(["- A", "- A", "- A"]) == ["- A"]


def test_empty_list_dedupes_to_empty():
    assert orchestrator.dedupe_bounded([]) == []


# ---- dedupe_bounded: bound caps to the last `limit`
def test_bound_caps_to_limit_keeping_newest():
    bullets = [f"- b{i}" for i in range(20)]
    out = orchestrator.dedupe_bounded(bullets, limit=15)
    assert len(out) == 15
    assert out == [f"- b{i}" for i in range(5, 20)]  # the last 15


def test_bound_default_limit_is_15():
    bullets = [f"- b{i}" for i in range(30)]
    assert len(orchestrator.dedupe_bounded(bullets)) == 15


def test_under_limit_keeps_all():
    bullets = [f"- b{i}" for i in range(5)]
    assert orchestrator.dedupe_bounded(bullets, limit=15) == bullets


def test_dedup_then_bound_uses_deduped_count():
    # 18 raw bullets but only 12 distinct -> under a limit of 15, all 12 survive.
    raw = [f"- b{i}" for i in range(12)] + [f"- b{i}" for i in range(6)]
    out = orchestrator.dedupe_bounded(raw, limit=15)
    assert len(out) == 12


# ---- append_learned round-trip (IO wrapper over the two pure helpers)
def test_append_learned_creates_and_normalizes(tmp_path):
    f = tmp_path / "learned.md"
    orchestrator.append_learned(str(f), "use   pnpm")
    assert f.read_text(encoding="utf-8") == "- use pnpm\n"


def test_append_learned_dedupes_and_bounds(tmp_path):
    f = tmp_path / "learned.md"
    for i in range(20):
        orchestrator.append_learned(str(f), f"convention {i}")
    orchestrator.append_learned(str(f), "convention 0")  # re-surface an old one
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 15
    assert lines[-1] == "- convention 0"          # re-learned -> newest position
    assert "- convention 19" in lines
