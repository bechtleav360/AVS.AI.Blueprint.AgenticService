"""Main entry point for the customer support Q&A collaboration example."""

from pathlib import Path

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from blueprint.agents.base import AgentRuntime

from .handlers.agent_invoker import AgentInvokerHandler
from .api import SupportQARestApi
from .services import SupportQAService

config = Config(
    settings_files=[
        "settings.toml",
        "secrets.toml",
    ],
    root_path=Path(__file__).parent.parent,
)

config.get_event_publishing_config()

junior_agent: AgentRuntime = (
    AgentBuilder(config, runtime_name="junior_support")
    .with_model_from_config()
    .with_system_prompt("junior_system")
    .build(name="junior_support")
)

senior_agent: AgentRuntime = (
    AgentBuilder(config, runtime_name="senior_support")
    .with_model_from_config()
    .with_system_prompt("senior_system")
    .build(name="senior_support")
)

app = (
    AppBuilder(config=config)
    .with_cache()
    .with_agent(junior_agent)
    .with_agent(senior_agent)
    .with_handler(AgentInvokerHandler)
    .with_service(SupportQAService())
    .with_rest_api(SupportQARestApi())
    .build()
)
