"""Tests for the unblock subcommand's pure clear_blocked helper."""
import orchestrator


def _results():
    return {
        "T1": {"status": "done", "commit": "abc123def", "title": "shipped"},
        "T2": {"status": "blocked", "reason": "gate never passed", "title": "b1"},
        "T3": {"status": "blocked", "reason": "likely stuck", "title": "b2"},
    }


def test_all_blocked_cleared_done_survives():
    out = orchestrator.clear_blocked(_results())
    assert set(out) == {"T1"}
    assert out["T1"]["status"] == "done"


def test_single_id_cleared():
    out = orchestrator.clear_blocked(_results(), "T2")
    assert set(out) == {"T1", "T3"}
    assert out["T3"]["status"] == "blocked"


def test_done_id_not_cleared_even_when_named():
    results = _results()
    out = orchestrator.clear_blocked(results, "T1")
    assert out == results


def test_unknown_id_is_noop():
    results = _results()
    out = orchestrator.clear_blocked(results, "T9")
    assert out == results


def test_input_dict_not_mutated():
    results = _results()
    snapshot = {tid: dict(r) for tid, r in results.items()}
    out = orchestrator.clear_blocked(results)
    assert results == snapshot
    assert out is not results
