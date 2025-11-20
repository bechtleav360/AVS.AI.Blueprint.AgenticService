"""Pytest configuration for simple_event_processor example."""

import sys
from pathlib import Path

# Add the example's src directory to the path
example_src = Path(__file__).parent / "src"
if str(example_src) not in sys.path:
    sys.path.insert(0, str(example_src))
