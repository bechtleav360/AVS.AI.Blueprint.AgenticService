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
    AssetFetchHandler,
    AssetHarmonizingHandler,
    AssetTagUpdateHandler,
)
from .models import Asset, AssetTaggingOutput
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

# Build invoice analyzer agent
asset_tagging_agent: Agent = (
    AgentBuilder(config, runtime_name="asset_tagging")
    .with_model_from_config("asset_tagging")
    .with_system_prompt_file("asset_tagging")
    .with_tools(
        [
            Tool(
                name="calculate_invoice",
                function=InvoiceProcessingLogic.calculate_invoice_tool,
            )
        ]
    )
    .with_result_type(AssetTaggingOutput)
    .build(name="asset_tagging")
)

# Build harmonizing agent
asset_harmonizing_agent: Agent = (
    AgentBuilder(config, runtime_name="asset_harmonizing")
    .with_model_from_config(runtime_name="asset_harmonizing")
    .with_system_prompt_file(
        prompt_name="asset_harmonizing", runtime_name="asset_harmonizing"
    )
    .with_result_type(Asset)
    .build()
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
    .with_handler(AssetFetchHandler)
    .with_handler(AgentInvokerHandler)
    .with_handler(AssetHarmonizingHandler)
    .with_handler(AssetTagUpdateHandler)
    .with_rest_api(CustomRestApi)
    .with_agent(asset_tagging_agent)
    .with_agent(asset_harmonizing_agent)
    .build()
)
