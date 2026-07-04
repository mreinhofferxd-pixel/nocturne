"""End-to-end exercise of the §9 rate-limit DETECTION off a streamed stream-json.

The pure parsers (parse_events / is_rate_limited / rate_limit_reset) have unit
coverage in test_rate_limit.py, but they are called there on hand-built strings --
the real seam, run_claude's Popen streaming loop that captures the live line-by-line
stream and feeds it to those parsers, had no coverage and has never fired on a real
429 (the dogfood that hit one was wiped before the stream was saved).

These tests drive run_claude with a faked Popen whose stdout replays a faithful
canned stream (event shapes mirror captured real logs: `result` carries
`api_error_status` + `total_cost_usd`, confirmed from .loop/log). They prove the
streamed rate_limit_event / 429-result actually reaches ClaudeResult, and that the
resulting ClaudeResult drives the pause-vs-halt decision (handle_rate_limit).
"""
import subprocess

import orchestrator
import pytest

CFG = {
    "guardrails": {"allowed_tools": ["Edit", "Bash"]},
    "model": "claude-opus-4-8",
    "budget": {"max_turns": 5, "max_seconds_per_task": 1800},
}

# Faithful canned streams (one JSON event per line, as claude -p --stream-json emits).
INIT = '{"type":"system","subtype":"init","model":"claude-opus-4-8"}'
SAY = '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}'
REJECTED = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":1000,"rateLimitType":"five_hour"}}'
)
RESULT_429 = (
    '{"type":"result","subtype":"error_during_execution","is_error":true,'
    '"api_error_status":429,"total_cost_usd":0.0,"num_turns":1}'
)
RESULT_OK = (
    '{"type":"result","subtype":"success","is_error":false,'
    '"api_error_status":null,"total_cost_usd":0.5,"num_turns":3}'
)


class _FakeStdin:
    def __init__(self, captured):
        self._captured = captured

    def write(self, s):
        self._captured["prompt"] = s

    def close(self):
        pass


class _FakeProc:
    def __init__(self, lines, captured):
        self.stdin = _FakeStdin(captured)
        # run_claude iterates `for line in proc.stdout`; a list of newline-terminated
        # strings replays the stream exactly once, like a real pipe.
        self.stdout = [ln + "\n" for ln in lines]
        self.returncode = 0

    def wait(self):
        return 0

    def kill(self):
        pass


@pytest.fixture
def stream(monkeypatch, tmp_path):
    """Return a runner that streams `lines` through run_claude via a faked Popen,
    isolating the activity/learned side-files to tmp so the real repo is untouched."""
    monkeypatch.setattr(orchestrator, "ACTIVITY", tmp_path / "activity.log")
    monkeypatch.setattr(orchestrator, "LEARNED", tmp_path / "learned.md")
    captured = {}

    def run(lines):
        def factory(cmd, **kwargs):
            captured["cmd"] = cmd
            return _FakeProc(lines, captured)

        monkeypatch.setattr(subprocess, "Popen", factory)
        logfile = tmp_path / "iter.md"
        result = orchestrator.run_claude("do the task", CFG, logfile)
        return result, logfile, captured

    return run


def test_streamed_rate_limit_event_detected(stream):
    result, logfile, captured = stream([INIT, SAY, REJECTED, RESULT_429])
    assert result.rate_limited is True
    assert result.resets_at == 1000          # resetsAt pulled off the rejected event
    assert result.cost == 0.0
    assert captured["prompt"] == "do the task"          # prompt reached stdin
    assert "rate_limit_event" in logfile.read_text(encoding="utf-8")  # stream logged


def test_streamed_429_result_fallback_detected(stream):
    # No rate_limit_event -- detection must fall back to the terminal result's
    # api_error_status==429 (a real field, confirmed from captured logs). No reset hint.
    result, _, _ = stream([INIT, RESULT_429])
    assert result.rate_limited is True
    assert result.resets_at is None


def test_streamed_success_is_not_rate_limited(stream):
    result, logfile, _ = stream([INIT, SAY, RESULT_OK])
    assert result.rate_limited is False
    assert result.cost == 0.5
    assert result.resets_at is None
    assert logfile.read_text(encoding="utf-8").count("\n") == 3   # every line written


def test_streamed_detection_drives_pause_and_halt(stream):
    # The detected ClaudeResult must drive the §9 decision end-to-end: pause-resume
    # sleeps until reset+buffer; halt raises RateLimitHalt.
    result, _, _ = stream([INIT, REJECTED, RESULT_429])
    wait = orchestrator.handle_rate_limit(result, {}, now=990)
    assert wait == (1000 - 990) + orchestrator.RATE_LIMIT_BUFFER_S
    with pytest.raises(orchestrator.RateLimitHalt):
        orchestrator.handle_rate_limit(result, {"on_rate_limit": "halt"}, now=990)
