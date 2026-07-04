"""Tests for per-task model tiering + retry escalation (spec §8.4)."""
import orchestrator
from markdown_adapter import Task

CFG = {"model": "claude-opus-4-8"}


def _task(title):
    return Task(index=0, title=title, done=False, raw="")


# ---- tier tag parsing
def test_parse_tier_simple():
    assert orchestrator.parse_tier("do a thing [simple]") == "simple"


def test_parse_tier_complex():
    assert orchestrator.parse_tier("middling thing [complex]") == "complex"


def test_parse_tier_very_complex():
    # "complex" is a substring of "very-complex"; the whole tag must win.
    assert orchestrator.parse_tier("hard thing [very-complex]") == "very-complex"


def test_parse_tier_none_when_untagged():
    assert orchestrator.parse_tier("untagged task") is None


def test_parse_tier_case_insensitive():
    assert orchestrator.parse_tier("thing [Simple]") == "simple"


def test_parse_tier_only_trailing_tag():
    # A bracketed word mid-title is not a complexity tag.
    assert orchestrator.parse_tier("wire [simple] auth then log") is None


# ---- tier -> model mapping
def test_pick_model_simple_maps_to_sonnet():
    assert orchestrator.pick_model(_task("x [simple]"), CFG) == "claude-sonnet-5"


def test_pick_model_complex_maps_to_opus():
    assert orchestrator.pick_model(_task("x [complex]"), CFG) == "claude-opus-4-8"


def test_pick_model_very_complex_maps_to_fable():
    assert orchestrator.pick_model(_task("x [very-complex]"), CFG) == "claude-fable-5"


def test_pick_model_untagged_uses_config_default():
    assert orchestrator.pick_model(_task("x"), {"model": "cfg-default"}) == "cfg-default"


def test_pick_model_untagged_falls_to_builtin_default():
    assert orchestrator.pick_model(_task("x"), {}) == orchestrator.DEFAULT_MODEL


def test_pick_model_config_overrides_tier():
    cfg = {"model": "claude-opus-4-8", "tier_models": {"simple": "custom-cheap"}}
    assert orchestrator.pick_model(_task("x [simple]"), cfg) == "custom-cheap"


# ---- retry escalation ladder: sonnet-5 -> opus-4-8 -> fable-5
def test_escalate_sonnet_to_opus():
    assert orchestrator.escalate("claude-sonnet-5", CFG) == "claude-opus-4-8"


def test_escalate_opus_to_fable():
    assert orchestrator.escalate("claude-opus-4-8", CFG) == "claude-fable-5"


def test_escalate_fable_stays_at_top():
    assert orchestrator.escalate("claude-fable-5", CFG) == "claude-fable-5"


def test_escalate_offladder_model_unchanged():
    assert orchestrator.escalate("some-custom-model", CFG) == "some-custom-model"


def test_escalate_respects_config_ladder():
    cfg = {"escalation_ladder": ["a", "b", "c"]}
    assert orchestrator.escalate("a", cfg) == "b"
    assert orchestrator.escalate("c", cfg) == "c"
