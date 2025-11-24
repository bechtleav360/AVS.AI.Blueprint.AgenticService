"""Main entry point for the REST microservice."""

from pathlib import Path


from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

from .api import CalculatorRestApi
from .services import CalculatorService

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
# Step 2: Build App with Custom REST API
# ============================================================================

# Create the REST API instance (AppBuilder will wire the registry into it)
calculator_api = CalculatorRestApi()
calculator_service = CalculatorService()

app = AppBuilder(config=config).with_rest_api(calculator_api).with_service(calculator_service).build()
