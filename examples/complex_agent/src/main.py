"""
Main entry point for the agent service.

This file constructs the FastAPI application from the base framework and wires in
custom routes/components. This way, the base framework has NO dependencies on the
custom agent code, but most logic remains in `base`.
"""

from pathlib import Path

from pydantic_ai import Agent, Tool

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

from .api.rest import CustomRestApi
from .handlers import AgentInvokerHandler, SimpleProcessorHandler
from .models.results import InvoiceAnalysisOutput
from .services import InvoiceProcessingLogic

# Optional: Import OpenTelemetry for metrics (uncomment if using OTEL)
# from opentelemetry import metrics

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

# Optional: Get OpenTelemetry meter for metrics recording
# Uncomment if using OpenTelemetry:
# meter = metrics.get_meter(__name__)

# Build invoice analyzer agent
# Note: Pass meter=meter to AgentBuilder if using OpenTelemetry
invoice_agent: Agent = (
    AgentBuilder(config, runtime_name="invoice_analyzer")  # Add meter=meter if using OTEL
    .with_model_from_config("invoice_analyzer")
    .with_system_prompt_file("instruction")
    .with_tools(
        [
            Tool(
                name="calculate_invoice",
                function=InvoiceProcessingLogic.calculate_invoice_tool,
            )
        ]
    )
    .with_result_type(InvoiceAnalysisOutput)
    .build(name="invoice_analyzer")
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
    .with_handler(AgentInvokerHandler)
    .with_handler(SimpleProcessorHandler)
    .with_rest_api(CustomRestApi())
    .with_agent(invoice_agent)
    .build()
)
