"""Factory for creating and configuring Pydantic AI Agent instances."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model

logger = logging.getLogger(__name__)


class AgentFactoryStrategy(ABC):
    """Abstract strategy for creating AI agents."""

    @abstractmethod
    def create_agent(
        self,
        model: Model,
        tools: List[Tool],
        system_prompt: str,
        deps_type: Type[Any],
        result_type: Optional[Type[BaseModel]] = None,
    ) -> Agent:
        """Create a configured Agent instance.

        Args:
            model: Configured Model instance.
            tools: List of tools available to the agent.
            system_prompt: System prompt text.
            deps_type: Type for the agent's dependencies/context.
            result_type: Optional result type for structured output.

        Returns:
            Configured Agent instance.
        """
        pass


class AgentFactory:
    """Factory for creating configured Agent instances based on provider type."""

    _factories: Dict[str, AgentFactoryStrategy] = {}

    @classmethod
    def _ensure_factories_loaded(cls) -> None:
        """Lazy load factory implementations to avoid circular imports."""
        if not cls._factories:
            from .providers import OpenAIAgentFactory, VLLMAgentFactory

            cls._factories["openai"] = OpenAIAgentFactory()
            cls._factories["vllm"] = VLLMAgentFactory()

    @classmethod
    def create_agent(
        cls,
        model: Model,
        provider_name: str,
        tools: List[Tool],
        system_prompt: str,
        deps_type: Type[Any],
        result_type: Optional[Type[BaseModel]] = None,
    ) -> Agent:
        """Create a configured Agent instance.

        Args:
            model: Configured Model instance from ModelProviderFactory.
            provider_name: Name of the provider ('openai', 'vllm', etc.).
            tools: List of tools available to the agent.
            system_prompt: System prompt text.
            deps_type: Type for the agent's dependencies/context.
            result_type: Optional result type for structured output.
                        Only used for providers that support output_type.

        Returns:
            Configured Agent instance.
        """
        cls._ensure_factories_loaded()
        factory = cls._factories.get(provider_name)
        if factory is None:
            logger.warning(
                "Unknown provider '%s', using OpenAI-style configuration", provider_name
            )
            factory = cls._factories["openai"]

        return factory.create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            deps_type=deps_type,
            result_type=result_type,
        )

    @classmethod
    def register_factory(
        cls,
        provider_name: str,
        factory: AgentFactoryStrategy,
    ) -> None:
        """Register a custom agent factory strategy.

        Args:
            provider_name: Unique identifier for the provider.
            factory: AgentFactoryStrategy implementation.
        """
        cls._factories[provider_name] = factory
        logger.info("Registered custom agent factory: %s", provider_name)
