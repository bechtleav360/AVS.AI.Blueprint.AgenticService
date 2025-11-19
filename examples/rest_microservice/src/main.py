"""Main entry point for the REST microservice."""

from pathlib import Path

from blueprint.agents.app_builder import AppBuilder

from .api import CalculatorRestApi

# Define the project root and paths to configuration files
project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# ============================================================================
# Build App with Custom REST API
# ============================================================================

# Create the REST API instance (AppBuilder will wire the registry into it)
calculator_api = CalculatorRestApi()

app = AppBuilder(settings_files=settings_files, root_path=project_root).with_rest_api(calculator_api).build()
