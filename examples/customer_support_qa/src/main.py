"""Main entry point for the customer support Q&A collaboration example."""

from pathlib import Path

from examples.customer_support_qa.src.handlers.agent_invoker import AgentInvokerHandler
from src.blueprint.agents.agent import AgentBuilder
from src.blueprint.agents.app_builder import AppBuilder
from src.blueprint.agents.config import Config

from examples.customer_support_qa.src.api import SupportQARestApi
from examples.customer_support_qa.src.services import SupportQAService

config = Config(
    settings_files=[
        "settings.toml",
        "secrets.toml",
    ],
    root_path=Path(__file__).parent.parent,
)

# Build the app first — this injects shared config so AI clients can use self.config
app = (
    AppBuilder(config=config)
    .with_cache()
    .with_handler(AgentInvokerHandler)
    .with_service(SupportQAService())
    .with_rest_api(SupportQARestApi())
    .build()
)

# Agents are built after config injection and auto-register into the shared registry
(
    AgentBuilder(config, runtime_name="junior_support")
    .with_model_from_config()
    .with_system_prompt("junior_system")
    .build(name="junior_support")
)

(
    AgentBuilder(config, runtime_name="senior_support")
    .with_model_from_config()
    .with_system_prompt("senior_system")
    .build(name="senior_support")
)
