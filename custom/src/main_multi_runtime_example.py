"""
Example main.py showing how to register multiple agent runtimes.

This demonstrates how to configure multiple runtime instances with different
configurations for different use cases.
"""

from pathlib import Path

from base.src.app_builder import AppBuilder

from .agent.runtime import AgentRuntime
from .api.rest import CustomRestApi
from .handlers import AgentInvokerHandler, SimpleProcessorHandler

# Define the project root and paths to your custom settings files
project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# Example 1: Register multiple runtimes with different names
# Each runtime will use its corresponding [runtime.{name}] configuration section
app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_handler(AgentInvokerHandler)
    .with_handler(SimpleProcessorHandler)
    
    # Register invoice analyzer runtime (default)
    # Uses [runtime.invoice_analyzer] config section
    .with_agent_runtime(
        AgentRuntime,
        name="invoice_analyzer",
        is_default=True
    )
    
    # Register document classifier runtime
    # Uses [runtime.document_classifier] config section
    .with_agent_runtime(
        AgentRuntime,
        name="document_classifier"
    )
    
    # Register summarizer runtime
    # Uses [runtime.summarizer] config section
    .with_agent_runtime(
        AgentRuntime,
        name="summarizer"
    )
    
    # Register validator runtime
    # Uses [runtime.validator] config section
    .with_agent_runtime(
        AgentRuntime,
        name="validator"
    )
    
    .with_rest_api(CustomRestApi)
    .build()
)

# Example 2: Using specialized runtime subclasses (optional)
# You can also create specialized runtime classes for different purposes

# from .agent.specialized_runtimes import (
#     InvoiceAnalyzerRuntime,
#     DocumentClassifierRuntime,
#     SummarizerRuntime
# )
#
# app = (
#     AppBuilder(settings_files=settings_files, root_path=project_root)
#     .with_handler(AgentInvokerHandler)
#     .with_handler(SimpleProcessorHandler)
#     
#     # Each specialized class can have its own tools and behavior
#     .with_agent_runtime(InvoiceAnalyzerRuntime, name="invoice_analyzer", is_default=True)
#     .with_agent_runtime(DocumentClassifierRuntime, name="document_classifier")
#     .with_agent_runtime(SummarizerRuntime, name="summarizer")
#     
#     .with_rest_api(CustomRestApi)
#     .build()
# )

__all__ = ["app"]
