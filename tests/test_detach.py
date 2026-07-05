"""Section-11 detach lifecycle: platform spawn kwargs and the handoff notice.
The OS-spawn itself is exercised by hand (weak pytest teeth by design)."""
import orchestrator as o


def test_detach_kwargs_windows_flags():
    kw = o._detach_kwargs(True)
    assert kw == {
        "creationflags": o.DETACHED_PROCESS | o.CREATE_NEW_PROCESS_GROUP,
    }


def test_detach_kwargs_posix_session():
    assert o._detach_kwargs(False) == {"start_new_session": True}


def test_detach_notice_names_pid_log_and_surfaces():
    msg = o.detach_notice(4242, ".loop/detached.log")
    assert "4242" in msg
    assert ".loop/detached.log" in msg
    assert "events.log" in msg
    assert "stop" in msg


def test_detach_notice_is_pure_and_multiline():
    assert o.detach_notice(1, "x") == o.detach_notice(1, "x")
    assert len(o.detach_notice(1, "x").splitlines()) == 4
