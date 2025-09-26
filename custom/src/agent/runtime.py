"""Customizable implementation of the Pydantic AI agent runtime."""

import logging
from typing import Any

from base.src.agent.base.runtime import BaseAgent
from ..config import CustomConfig

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

    def __init__(self, settings: CustomConfig):
        """Initialize the generic agent."""
        super().__init__(settings)

    def _get_prompt_name(self) -> str:
        """Return the name of the prompt file to use."""
        return "system"

    def _get_tools(self) -> list[Any]:
        """
        Return a list of tools for the AI agent.

        This method instantiates the Tools class and returns a list of its
        methods, which will be registered with the agent.
        """
        tools = Tools()
        return [tools.analyze_resource]

    def _get_processing_context_type(self) -> type[ProcessingContext]:
        """Return the type for the processing context dependencies."""
        return ProcessingContext

    def _get_result_type(self) -> type[CustomAgentOutput]:
        """Return the custom result model type for typed outputs."""
        return CustomAgentOutput

    async def _process_request(self, prompt: str, context: dict[str, Any] | None) -> CustomAgentOutput:
        # Run the agent via base helper; returns a response with typed .output
        resp = await self.run_with_agent(prompt, deps=context)
        output: CustomAgentOutput = resp.output  # parsed/validated as CustomAgentOutput
        # Optionally post-process:
        # output.confidence = output.confidence or 0.9
        # output.metadata = {**(output.metadata or {}), "source": "agent-v1"}
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
