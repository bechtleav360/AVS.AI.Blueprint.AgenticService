"""
Main entry point for the agent service.

This file constructs the FastAPI application from the base framework and wires in
custom routes/components. This way, the base framework has NO dependencies on the
custom agent code, but most logic remains in `base`.
"""

from pathlib import Path

from pydantic_ai import Agent, Tool

from base.src.agent import AgentBuilder
from base.src.app_builder import AppBuilder
from base.src.config import Config

from .api.rest import CustomRestApi
from .handlers import (
    AgentInvokerHandler,
    AssetPreprocessingHandler,
    AssetHarmonizedEventPublisher,
)
from .models import AssetHarmonizingOutput
from .services import InvoiceProcessingLogic

# Define the project root and paths to your custom settings files
project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# ============================================================================
# Step 1: Build Agents
# ============================================================================

# Load configuration
config = Config(settings_files=settings_files, root_path=project_root)



# Build harmonizing agent
asset_harmonizing_agent: Agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt_file(prompt_name="asset_harmonizing")
    .with_result_type(AssetHarmonizingOutput)
    .build(name="asset_harmonizing")
)

# Add more agents here as needed
# document_agent = (
#     AgentBuilder(config, runtime_name="document_classifier")
#     .with_model_from_config("document_classifier")
#     .with_system_prompt_file("document_classifier")
#     .build()
# )

# ============================================================================
# Step 2: Build App and Register Agents
# ============================================================================

app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_handler(AssetPreprocessingHandler)      # Runs first (priority=10)
    .with_handler(AgentInvokerHandler)            # Runs second (priority=20)
    .with_handler(AssetHarmonizedEventPublisher)  # Runs third (priority=40) - publishes result
    .with_rest_api(CustomRestApi)
    .with_agent(asset_harmonizing_agent)
    .build()
)

