"""
Main entry point for the agent service.

This file constructs the FastAPI application from the base framework and wires in
custom routes/components. This way, the base framework has NO dependencies on the
custom agent code, but most logic remains in `base`.
"""

from pathlib import Path

from base.src.app_builder import AppBuilder

from .agent.runtime import AgentRuntime
from .api.rest import CustomRestApi

# Import custom components to be injected
from .handlers import AgentInvokerHandler, SimpleProcessorHandler

# Define the project root and paths to your custom settings files
project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# Uvicorn entrypoint: create the app with custom configuration and components
app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_handler(AgentInvokerHandler)
    .with_handler(SimpleProcessorHandler)
    .with_agent_runtime(AgentRuntime, is_default=True)
    .with_rest_api(CustomRestApi)
    .build()
)


__all__ = ["app"]
