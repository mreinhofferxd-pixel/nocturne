"""Tests for the §9 rate-limit pause-resume backoff (orchestrator pure helpers).

A rate-limit rejection must NOT be treated as a gate/task failure: it should not
burn retries or falsely block a task. These pin the detection + wait arithmetic +
pause/halt decision without ever sleeping (`now` is passed in).

The streaming I/O in run_claude and the sleep in process_task are not unit-tested
(they spawn a subprocess / block); the classifiers below are where the logic lives.
"""
import pytest

import orchestrator as o

# The two signal shapes the harness must recognize, captured verbatim from a live
# org five-hour rejection.
REJECT_LINE = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":1000,"rateLimitType":"five_hour"}}'
)
RESULT_429 = '{"type":"result","is_error":true,"api_error_status":429,"subtype":"error"}'


# ---------------------------------------------------------------- parse_events
def test_parse_events_skips_non_json_and_bad_json():
    stdout = "\n".join([
        "not json",
        '{"type":"system","subtype":"init"}',
        "{ broken",
        '{"type":"result","total_cost_usd":0.5}',
    ])
    events = o.parse_events(stdout)
    assert [e["type"] for e in events] == ["system", "result"]


def test_parse_events_empty():
    assert o.parse_events("") == []
    assert o.parse_events(None) == []


def test_parse_cost_reads_events():
    events = o.parse_events(
        '{"type":"result","total_cost_usd":0.42,"subtype":"success"}'
    )
    assert o.parse_cost(events) == 0.42


# ---------------------------------------------------------------- is_rate_limited
def test_rate_limit_event_rejected_detected():
    assert o.is_rate_limited(o.parse_events(REJECT_LINE)) is True


def test_result_429_detected():
    assert o.is_rate_limited(o.parse_events(RESULT_429)) is True


def test_both_signals_together_detected():
    assert o.is_rate_limited(o.parse_events(REJECT_LINE + "\n" + RESULT_429)) is True


def test_allowed_rate_limit_event_not_flagged():
    ev = '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}'
    assert o.is_rate_limited(o.parse_events(ev)) is False


def test_normal_successful_stream_not_flagged():
    stdout = "\n".join([
        '{"type":"system","subtype":"init","model":"claude-opus-4-8"}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}',
        '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.1}',
    ])
    assert o.is_rate_limited(o.parse_events(stdout)) is False


def test_non_429_error_result_not_flagged():
    # A normal error result (e.g. gate failure surfaced as error) is not a rate limit.
    ev = '{"type":"result","is_error":true,"api_error_status":500}'
    assert o.is_rate_limited(o.parse_events(ev)) is False


def test_empty_events_not_flagged():
    assert o.is_rate_limited([]) is False


# ---------------------------------------------------------------- rate_limit_reset
def test_reset_extracted_from_rejected_event():
    assert o.rate_limit_reset(o.parse_events(REJECT_LINE)) == 1000


def test_reset_takes_last_rejected_value():
    a = REJECT_LINE
    b = REJECT_LINE.replace("1000", "2000")
    assert o.rate_limit_reset(o.parse_events(a + "\n" + b)) == 2000


def test_reset_none_when_only_429_result():
    # A bare 429 result carries no resetsAt hint.
    assert o.rate_limit_reset(o.parse_events(RESULT_429)) is None


def test_reset_none_when_allowed_only():
    ev = '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":50}}'
    assert o.rate_limit_reset(o.parse_events(ev)) is None


# ---------------------------------------------------------------- wait_seconds
def test_wait_future_reset_adds_buffer():
    assert o.wait_seconds(1000, 900) == 100 + o.RATE_LIMIT_BUFFER_S


def test_wait_past_reset_is_just_buffer_never_negative():
    assert o.wait_seconds(1000, 5000) == o.RATE_LIMIT_BUFFER_S


def test_wait_none_reset_is_just_buffer():
    assert o.wait_seconds(None, 5000) == o.RATE_LIMIT_BUFFER_S


def test_wait_custom_buffer():
    assert o.wait_seconds(1000, 900, buffer_s=0) == 100


def test_wait_uses_passed_now_not_wallclock():
    # Same reset, two different `now` values -> two different waits (proves `now`
    # drives the arithmetic, no time.time() inside).
    assert o.wait_seconds(1000, 990) != o.wait_seconds(1000, 900)


# ---------------------------------------------------------------- handle_rate_limit
def _result(resets_at=1000):
    return o.ClaudeResult(cost=0.0, rate_limited=True, resets_at=resets_at)


def test_handle_pause_resume_returns_wait():
    wait = o.handle_rate_limit(_result(1000), {}, now=900)  # default policy
    assert wait == 100 + o.RATE_LIMIT_BUFFER_S


def test_handle_halt_policy_raises():
    with pytest.raises(o.RateLimitHalt) as ei:
        o.handle_rate_limit(_result(1000), {"on_rate_limit": "halt"}, now=900)
    assert ei.value.resets_at == 1000


def test_handle_wait_over_cap_raises_even_when_pause_resume():
    with pytest.raises(o.RateLimitHalt):
        o.handle_rate_limit(
            _result(100000), {"max_rate_limit_wait_s": 60}, now=0
        )


def test_handle_wait_within_cap_returns_wait():
    wait = o.handle_rate_limit(
        _result(1000), {"max_rate_limit_wait_s": 10000}, now=900
    )
    assert wait == 100 + o.RATE_LIMIT_BUFFER_S


def test_handle_cap_none_never_raises_on_cap():
    wait = o.handle_rate_limit(
        _result(100000), {"max_rate_limit_wait_s": None}, now=0
    )
    assert wait == 100000 + o.RATE_LIMIT_BUFFER_S


def test_handle_default_cap_covers_five_hour_reset():
    # A five_hour limit resets up to ~5h out; the default cap must pause, not halt.
    five_hours = 5 * 3600
    wait = o.handle_rate_limit(_result(five_hours), {}, now=0)
    assert wait == five_hours + o.RATE_LIMIT_BUFFER_S
    assert wait <= o.DEFAULT_MAX_RATE_LIMIT_WAIT_S


# ---------------------------------------------------------------- halt message
def test_halt_msg_includes_resume_command():
    msg = o._rate_limit_halt_msg(1000)
    assert "python .loop/orchestrator.py" in msg


def test_halt_msg_handles_missing_reset():
    msg = o._rate_limit_halt_msg(None)
    assert "python .loop/orchestrator.py" in msg
