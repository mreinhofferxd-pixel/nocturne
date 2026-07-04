"""Stream-json VALUES that arrive null or garbage must degrade, never crash
(section 9 parse layer). Field PRESENCE is covered in test_rate_limit.py; these
pin the value edge cases: a present-but-null total_cost_usd and a non-numeric
resetsAt."""
import orchestrator as o


# ---------------------------------------------------------------- parse_cost
def test_parse_cost_null_cost_is_zero():
    events = o.parse_events('{"type":"result","total_cost_usd":null,"is_error":true}')
    assert o.parse_cost(events) == 0.0


def test_parse_cost_null_then_real_keeps_real():
    events = o.parse_events(
        '{"type":"result","total_cost_usd":null}\n'
        '{"type":"result","total_cost_usd":0.7}'
    )
    assert o.parse_cost(events) == 0.7


def test_parse_cost_stays_summable():
    events = o.parse_events('{"type":"result","total_cost_usd":null}')
    assert 1.0 + o.parse_cost(events) == 1.0  # never None -> no TypeError mid-run


# ---------------------------------------------------------------- wait_seconds
def test_wait_seconds_non_numeric_resets_at_degrades_to_buffer():
    assert o.wait_seconds("soon", now=1000) == o.RATE_LIMIT_BUFFER_S


def test_wait_seconds_list_resets_at_degrades_to_buffer():
    assert o.wait_seconds([1, 2], now=1000) == o.RATE_LIMIT_BUFFER_S


def test_wait_seconds_numeric_string_still_works():
    # int("1200") parses: a stringly-typed epoch is still honored
    assert o.wait_seconds("1200", now=1000) == 200 + o.RATE_LIMIT_BUFFER_S


def test_wait_seconds_normal_path_unchanged():
    assert o.wait_seconds(1200, now=1000) == 200 + o.RATE_LIMIT_BUFFER_S
