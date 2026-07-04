"""Make the skill's python modules importable from tests.

The harness + adapter live under the skill dir; add them to sys.path so tests can
import them directly (mirrors how they sit side-by-side in .loop/ at runtime).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "loop-creator"

for sub in ("adapters", "templates"):
    p = SKILL / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
