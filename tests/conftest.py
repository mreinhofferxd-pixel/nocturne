"""Make the skill's python modules importable from tests.

The harness + adapter live under the skill dir; add them to sys.path so tests can
import them directly (mirrors how they sit side-by-side in .loop/ at runtime).
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "nocturne"

for sub in ("adapters", "templates"):
    p = SKILL / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Prime the adapter import from the skill path. Importing orchestrator first
# would insert the runtime .loop/ dir (stale copies) ahead on sys.path and
# shadow the skill's markdown_adapter for every later import.
importlib.import_module("markdown_adapter")


@pytest.fixture(autouse=True)
def _nocturne_home(tmp_path, monkeypatch):
    """Hermetic run registry: every test writes heartbeats under a tmp dir,
    never the real ~/.nocturne (process_task heartbeats fire in many tests)."""
    monkeypatch.setenv("NOCTURNE_HOME", str(tmp_path / "nocturne-home"))
