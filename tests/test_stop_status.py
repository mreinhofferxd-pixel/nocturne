"""Tests for the stop/status subcommand helpers (spec §11)."""
import orchestrator


def test_cmd_stop_writes_sentinel(tmp_path, capsys):
    loop = tmp_path / ".loop"
    loop.mkdir()
    rc = orchestrator.cmd_stop(loop=loop)
    assert rc == 0
    assert (loop / "STOP").exists()
    assert "halt" in capsys.readouterr().out.lower()


def test_cmd_stop_notice_when_no_loop(tmp_path, capsys):
    loop = tmp_path / ".loop"  # deliberately not created
    rc = orchestrator.cmd_stop(loop=loop)
    assert rc == 1
    assert not (loop / "STOP").exists()
    assert "nothing to stop" in capsys.readouterr().out.lower()


def test_cmd_status_prints_report(tmp_path, capsys):
    report = tmp_path / "report.md"
    report.write_text("# loop-creator report\n- done: 3\n", encoding="utf-8")
    rc = orchestrator.cmd_status(report=report)
    assert rc == 0
    out = capsys.readouterr().out
    assert "loop-creator report" in out
    assert "done: 3" in out


def test_cmd_status_notice_when_no_report(tmp_path, capsys):
    report = tmp_path / "report.md"  # absent
    rc = orchestrator.cmd_status(report=report)
    assert rc == 0
    assert "no run yet" in capsys.readouterr().out.lower()
