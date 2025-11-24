"""Pytest configuration for trivia_game example."""

import sys
from pathlib import Path

# Add the workspace root to the path so 'examples' module can be imported
workspace_root = Path(__file__).parent.parent.parent
workspace_src = workspace_root / "src"

for path in (workspace_root, workspace_src):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Add the example's src directory to the path
example_src = Path(__file__).parent / "src"
if str(example_src) not in sys.path:
    sys.path.insert(0, str(example_src))
