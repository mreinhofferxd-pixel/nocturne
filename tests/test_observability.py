import types

import orchestrator as o


def test_feed_lines_tool_use_is_stamped():
    ev = {
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "symphony/webhook.py"}}
        ]},
    }
    assert o.feed_lines(ev, "12:00:00") == ["12:00:00 🔧 Edit: symphony/webhook.py"]


def test_feed_lines_result_carries_cost():
    ev = {"type": "result", "subtype": "success", "num_turns": 3, "total_cost_usd": 0.1234}
    lines = o.feed_lines(ev, "09:30:15")
    assert len(lines) == 1
    assert lines[0].startswith("09:30:15 ")
    assert "result: success" in lines[0]
    assert "$0.1234" in lines[0]


def test_feed_lines_allowed_rate_limit_is_silent():
    ev = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}
    assert o.feed_lines(ev, "00:00:00") == []


def test_feed_lines_rejected_rate_limit_shows():
    ev = {"type": "rate_limit_event",
          "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"}}
    assert o.feed_lines(ev, "01:02:03") == ["01:02:03 ⏳ RATE LIMITED (five_hour)"]


def test_task_banner_shape():
    task = types.SimpleNamespace(id="task-3", title="Harden webhook handler")
    line = o.task_banner(task, 2, 3, "claude-opus-4-8", 2.5)
    assert line == ("▶ task-3 'Harden webhook handler' · attempt 2/3 · "
                    "claude-opus-4-8 · $2.50")


def test_live_feed_default_on():
    # attached runs stream to stdout with no extra config
    assert o.LIVE_FEED is True
