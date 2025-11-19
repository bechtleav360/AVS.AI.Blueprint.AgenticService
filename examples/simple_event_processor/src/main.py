"""Main entry point for the simple event processor."""

from pathlib import Path

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

from .handlers import SimpleProcessorHandler

# Define the project root and paths to configuration files
project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# ============================================================================
# Step 1: Load Configuration
# ============================================================================

config = Config(settings_files=settings_files, root_path=project_root)

# ============================================================================
# Step 2: Build App with Handler
# ============================================================================

app = AppBuilder(settings_files=settings_files, root_path=project_root).with_handler(SimpleProcessorHandler).build()
