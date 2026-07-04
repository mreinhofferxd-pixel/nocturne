"""Tests for the activity-feed decoder (orchestrator._activity_line / _tool_summary).

Pure functions: stream-json event dict -> human-readable feed lines. The streaming
I/O in run_claude is not unit-tested (it spawns a subprocess), but the decode logic
that turns raw events into the readable feed is, since that is where bugs hide.
"""
import orchestrator as o


def test_init_event_names_model():
    ev = {"type": "system", "subtype": "init", "model": "claude-opus-4-8"}
    lines = o._activity_line(ev)
    assert len(lines) == 1
    assert "session start" in lines[0]
    assert "claude-opus-4-8" in lines[0]


def test_assistant_text_block():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Adding the   stop\nsubcommand now"},
    ]}}
    lines = o._activity_line(ev)
    assert lines == ["💬 Adding the stop subcommand now"]  # whitespace collapsed


def test_assistant_text_truncated():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "x" * 500},
    ]}}
    (line,) = o._activity_line(ev)
    assert len(line) <= 140 + 4  # emoji + space prefix, body capped at 140


def test_assistant_tool_use_bash_shows_command():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m x"}},
    ]}}
    (line,) = o._activity_line(ev)
    assert line == "🔧 Bash: git commit -m x"


def test_assistant_tool_use_edit_shows_path():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "orchestrator.py", "old_string": "a"}},
    ]}}
    (line,) = o._activity_line(ev)
    assert line == "🔧 Edit: orchestrator.py"


def test_assistant_multiple_blocks():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "done"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ruff check ."}},
    ]}}
    lines = o._activity_line(ev)
    assert lines == ["💬 done", "🔧 Bash: ruff check ."]


def test_result_ok_vs_error():
    ok = o._activity_line({"type": "result", "subtype": "success",
                           "num_turns": 5, "total_cost_usd": 0.42})
    assert ok[0].startswith("■") and "$0.4200" in ok[0]
    err = o._activity_line({"type": "result", "subtype": "success", "is_error": True,
                            "num_turns": 1, "total_cost_usd": 0})
    assert err[0].startswith("✖")


def test_rate_limit_rejected_flagged():
    ev = {"type": "rate_limit_event", "rate_limit_info": {
        "status": "rejected", "rateLimitType": "five_hour"}}
    (line,) = o._activity_line(ev)
    assert "RATE LIMITED" in line and "five_hour" in line


def test_rate_limit_allowed_is_silent():
    ev = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}
    assert o._activity_line(ev) == []


def test_unknown_event_is_silent():
    assert o._activity_line({"type": "user", "message": {}}) == []


def test_tool_summary_falls_back_to_name():
    assert o._tool_summary("Weird", {"no_known_key": 1}) == "Weird"
    assert o._tool_summary("Weird", "not-a-dict") == "Weird"
