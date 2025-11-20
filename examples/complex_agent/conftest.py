"""Pytest configuration for complex_agent example."""

import sys
from pathlib import Path

# Add the workspace root to the path so 'examples' module can be imported
workspace_root = Path(__file__).parent.parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

# Add the example's src directory to the path
example_src = Path(__file__).parent / "src"
if str(example_src) not in sys.path:
    sys.path.insert(0, str(example_src))
