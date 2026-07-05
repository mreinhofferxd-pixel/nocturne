"""Global append-only event feed: pure line format (detail collapse + 200-char
cap) and the append_event IO wrapper under a hermetic NOCTURNE_HOME."""
import orchestrator as o


def test_event_line_without_detail():
    assert (o.event_line("2026-07-05T01:02:03", "repo", "task-1", "TASK_DONE")
            == "2026-07-05T01:02:03 repo task-1 TASK_DONE")


def test_event_line_with_detail():
    assert (o.event_line("2026-07-05T01:02:03", "repo", "task-1", "TASK_DONE",
                         "abc123456 $0.4200")
            == "2026-07-05T01:02:03 repo task-1 TASK_DONE abc123456 $0.4200")


def test_event_line_collapses_detail_whitespace():
    line = o.event_line("t", "r", "id", "TASK_BLOCKED", " gate\nfailed\t  twice ")
    assert line == "t r id TASK_BLOCKED gate failed twice"


def test_event_line_caps_at_200_chars():
    line = o.event_line("t", "r", "id", "HALT", "x" * 500)
    assert len(line) == 200
    assert not line.endswith("\n")


def test_append_event_creates_file_then_appends(tmp_path, monkeypatch):
    monkeypatch.setenv("NOCTURNE_HOME", str(tmp_path))
    path = o.registry_dir() / "events.log"
    assert not path.exists()
    o.append_event(path, "line one")
    o.append_event(path, "line two")
    assert path.read_text(encoding="utf-8") == "line one\nline two\n"
