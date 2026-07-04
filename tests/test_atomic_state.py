"""Atomic state writes: a crash mid-write must never leave a torn state.json
(a torn file makes load_state raise on resume AND loses the branch pin, so the
next run would mint a fresh loop branch and abandon the old one's commits)."""
import json

import orchestrator
from orchestrator import _atomic_write_text


def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "state.json"
    _atomic_write_text(p, '{"a": 1}')
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_atomic_write_replaces_existing_content(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("old content", encoding="utf-8")
    _atomic_write_text(p, "new content")
    assert p.read_text(encoding="utf-8") == "new content"


def test_no_temp_file_left_behind(tmp_path):
    p = tmp_path / "state.json"
    _atomic_write_text(p, "data")
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]


def test_atomic_write_utf8(tmp_path):
    p = tmp_path / "state.json"
    _atomic_write_text(p, '{"title": "task \\u2192 done \\u00a79"}')
    assert "\\u2192" in p.read_text(encoding="utf-8")


def test_save_state_goes_through_atomic_writer(monkeypatch):
    calls = {}

    def fake(path, text):
        calls["path"] = path
        calls["text"] = text

    monkeypatch.setattr(orchestrator, "_atomic_write_text", fake)
    orchestrator.save_state({"x": 1})
    assert calls["path"] is orchestrator.STATE
    parsed = json.loads(calls["text"])
    assert parsed["x"] == 1
    assert "updated_at" in parsed
