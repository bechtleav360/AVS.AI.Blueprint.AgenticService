"""Model provider configuration strategies for different AI providers."""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

from pydantic_ai.models import Model

logger = logging.getLogger(__name__)


class ModelProviderStrategy(ABC):
    """Abstract strategy for configuring AI model providers."""

    @abstractmethod
    def create_model(self, ai_config: Dict[str, Any]) -> Model:
        """Create and configure the AI model based on provider-specific settings.

        Args:
            ai_config: Configuration dictionary containing provider settings.

        Returns:
            Configured Model instance.
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the provider name identifier."""
        pass


class ModelProviderFactory:
    """Factory for creating model provider strategies."""

    _providers: Dict[str, ModelProviderStrategy] = {}

    @classmethod
    def _ensure_providers_loaded(cls) -> None:
        """Lazy load provider implementations to avoid circular imports."""
        if not cls._providers:
            from .providers import OpenAIModelProvider, VLLMModelProvider
            cls._providers["openai"] = OpenAIModelProvider()
            cls._providers["vllm"] = VLLMModelProvider()

    @classmethod
    def get_provider(cls, provider_name: str) -> ModelProviderStrategy:
        """Get the appropriate model provider strategy.

        Args:
            provider_name: Name of the provider ('openai', 'vllm', etc.).

        Returns:
            ModelProviderStrategy instance.

        Raises:
            ValueError: If provider is not supported.
        """
        cls._ensure_providers_loaded()
        provider = cls._providers.get(provider_name)
        if provider is None:
            raise ValueError(
                f"Unsupported AI provider: {provider_name}. "
                f"Supported providers: {list(cls._providers.keys())}"
            )
        return provider

    @classmethod
    def register_provider(
        cls,
        provider_name: str,
        provider: ModelProviderStrategy
    ) -> None:
        """Register a custom model provider strategy.

        Args:
            provider_name: Unique identifier for the provider.
            provider: ModelProviderStrategy implementation.
        """
        cls._providers[provider_name] = provider
        logger.info("Registered custom model provider: %s", provider_name)

    @classmethod
    def create_model(cls, ai_config: Dict[str, Any]) -> Model:
        """Create a model using the appropriate provider strategy.

        Args:
            ai_config: Configuration dictionary with 'provider' key.

        Returns:
            Configured Model instance.
        """
        provider_name = ai_config.get("provider")
        if not provider_name:
            raise ValueError("AI configuration must specify 'provider'")

        provider = cls.get_provider(provider_name)
        return provider.create_model(ai_config)
