"""Smoke tests: the harness + adapter import and expose their core API."""


def test_adapter_imports():
    import markdown_adapter

    assert hasattr(markdown_adapter, "MarkdownBacklog")


def test_orchestrator_imports():
    import orchestrator

    for fn in ("run_gate", "build_prompt", "pick_task", "discard_inflight", "main"):
        assert hasattr(orchestrator, fn), fn
