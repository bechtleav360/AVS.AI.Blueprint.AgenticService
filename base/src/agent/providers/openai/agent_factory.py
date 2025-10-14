"""OpenAI agent factory implementation."""

import logging
from typing import Any, List, Optional, Type

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModelSettings

from ...agent_factory import AgentFactoryStrategy

logger = logging.getLogger(__name__)


class OpenAIAgentFactory(AgentFactoryStrategy):
    """Factory for creating OpenAI-configured agents."""

    def create_agent(
        self,
        model: Model,
        tools: List[Tool],
        system_prompt: str,
        deps_type: Type[Any],
        result_type: Optional[Type[BaseModel]] = None,
    ) -> Agent:
        """Create agent configured for OpenAI.

        OpenAI agents use output_type for structured output and
        tool_choice="auto" for flexible tool usage.

        Args:
            model: Configured Model instance.
            tools: List of tools available to the agent.
            system_prompt: System prompt text.
            deps_type: Type for the agent's dependencies/context.
            result_type: Optional result type for structured output.

        Returns:
            Configured Agent instance.
        """
        logger.info(
            "Creating OpenAI agent with %d tools and output_type=%s",
            len(tools),
            result_type.__name__ if result_type else "None",
        )

        return Agent(
            model=model,
            tools=tools,
            model_settings=OpenAIChatModelSettings(
                extra_body={"tool_choice": "auto"},
            ),
            deps_type=deps_type,
            output_type=result_type,
            system_prompt=system_prompt,
        )
