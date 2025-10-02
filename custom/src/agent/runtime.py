"""Customizable implementation of the Pydantic AI agent runtime."""

import logging
from typing import Any

from pydantic_ai import Tool

from base.src.agent import BaseAgent
from base.src.config import Config

from ..models.processing import ProcessingContext
from ..models.results import CustomAgentOutput
from .tools import Tools

logger = logging.getLogger(__name__)


class AgentRuntime(BaseAgent):
    """
    Customizable implementation of the agent runtime.

    This class provides concrete implementations for the abstract methods in
    BaseAgent. You should customize this class for your domain-specific
    requirements.
    """

    def __init__(self, settings: Config):
        """Initialize the generic agent."""
        super().__init__(settings)

    def _get_prompt_name(self) -> str:
        """Return the name of the prompt file to use."""
        return "system"

    def _get_tools(self) -> list[Tool]:
        """
        Return a list of tools for the AI agent.

        This method instantiates the Tools class and returns a list of its
        methods, which will be registered with the agent.
        """
        tools = Tools()
        return [Tool(name="analyze_resource", function=tools.analyze_resource)]

    def _get_processing_context_type(self) -> type[ProcessingContext]:
        """Return the type for the processing context dependencies."""
        return ProcessingContext

    def _get_result_type(self) -> type[CustomAgentOutput]:
        """Return the custom result model type for typed outputs."""
        return CustomAgentOutput

    def _handle_agent_response(self, agent_response: Any) -> CustomAgentOutput:
        """Extract the typed output from the agent response."""

        output: CustomAgentOutput = agent_response.output
        return output

    async def custom_health_check(self) -> bool:
        """
        Perform a custom, domain-specific health check.

        FIXME: Implement your custom health check logic here. This could include
        checking database connections, external API availability, or other
        dependencies.
        """
        # For this example, we'll just return True.
        return True
