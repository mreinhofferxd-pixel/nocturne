"""Global run-registry WRITE side: run_id sanitization, heartbeat payload shape,
atomic heartbeat file, and the NOCTURNE_HOME override that keeps tests hermetic
(never touch the real home)."""
import json

import orchestrator as o

EXPECTED_KEYS = {
    "run_id", "root", "branch", "pid", "status", "task_id", "task_title",
    "attempt", "model", "cost_usd", "done", "blocked", "todo", "updated_at",
}


def test_run_id_sanitizes_slash_and_space():
    assert (o.run_id("loop creator skill", "loop/20260705-023613")
            == "loop-creator-skill-20260705-023613")


def test_run_id_keeps_only_branch_tail():
    assert o.run_id("repo", "feature/deep/nest") == "repo-nest"


def test_heartbeat_record_key_completeness_and_truncation():
    rec = o.heartbeat_record(
        "rid", "/repo", "loop/x", 123, "running",
        "task-1", "t" * 200, 2, "claude-sonnet-5",
        1.5, 3, 1, 4, now=1000.0,
    )
    assert set(rec) == EXPECTED_KEYS
    assert rec["task_title"] == "t" * 80
    assert rec["updated_at"] == 1000.0
    assert rec["status"] == "running"
    assert (rec["done"], rec["blocked"], rec["todo"]) == (3, 1, 4)


def test_heartbeat_record_none_task_shape():
    rec = o.heartbeat_record(
        "rid", "/repo", "loop/x", 123, "halted",
        None, None, None, None, 0.0, 0, 0, 0, now=1.0,
    )
    assert set(rec) == EXPECTED_KEYS
    assert rec["task_id"] is None
    assert rec["task_title"] is None
    assert rec["attempt"] is None
    assert rec["model"] is None


def test_registry_dir_honors_override(tmp_path):
    assert o.registry_dir({"NOCTURNE_HOME": str(tmp_path)}) == tmp_path


def test_write_heartbeat_parseable_json_under_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NOCTURNE_HOME", str(tmp_path))
    rec = o.heartbeat_record(
        "rid", "/repo", "loop/x", 1, "running",
        None, None, None, None, 0.0, 0, 0, 2, now=5.0,
    )
    path = o.registry_dir() / "runs" / "rid.json"
    o.write_heartbeat(path, rec)
    assert json.loads(path.read_text(encoding="utf-8")) == rec
