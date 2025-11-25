"""Pytest configuration for simple_event_processor example."""

import sys
from pathlib import Path


def _add_path(path: Path) -> None:
    resolved = path.resolve()
    path_str = str(resolved)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


EXAMPLE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = EXAMPLE_DIR.parent.parent
WORKSPACE_SRC = WORKSPACE_ROOT / "src"

_add_path(WORKSPACE_ROOT)
_add_path(WORKSPACE_SRC)

EXAMPLE_SRC = EXAMPLE_DIR / "src"
_add_path(EXAMPLE_SRC)
