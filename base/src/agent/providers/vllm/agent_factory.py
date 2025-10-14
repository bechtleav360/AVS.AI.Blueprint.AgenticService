"""vLLM agent factory implementation."""

import logging
from typing import Any, List, Optional, Type

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model

from ...agent_factory import AgentFactoryStrategy

logger = logging.getLogger(__name__)


class VLLMAgentFactory(AgentFactoryStrategy):
    """Factory for creating vLLM-configured agents."""

    def create_agent(
        self,
        model: Model,
        tools: List[Tool],
        system_prompt: str,
        deps_type: Type[Any],
        result_type: Optional[Type[BaseModel]] = None,
    ) -> Agent:
        """Create agent configured for vLLM.

        vLLM agents don't use output_type to avoid response format issues.
        Tools return results naturally without forcing a schema.

        Args:
            model: Configured Model instance.
            tools: List of tools available to the agent.
            system_prompt: System prompt text.
            deps_type: Type for the agent's dependencies/context.
            result_type: Optional result type (ignored for vLLM).

        Returns:
            Configured Agent instance.
        """
        logger.info(
            "Creating vLLM agent with %d tools (no output_type constraint)", len(tools)
        )

        return Agent(
            model=model,
            tools=tools,
            deps_type=deps_type,
            system_prompt=system_prompt,
        )
