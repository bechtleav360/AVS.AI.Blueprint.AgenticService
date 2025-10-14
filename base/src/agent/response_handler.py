"""Response handler strategies for extracting results from different AI providers."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Type, TypeVar, Generic

from pydantic import BaseModel

from .providers import OpenAIResponseHandler, VLLMResponseHandler

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ResponseHandlerStrategy(ABC, Generic[T]):
    """Abstract strategy for handling AI model responses."""

    @abstractmethod
    def extract_result(self, agent_response: Any, result_type: Type[T]) -> T:
        """Extract the typed result from the agent response.
        
        Args:
            agent_response: Raw response from the agent.run() call.
            result_type: Expected Pydantic model type for the result.
            
        Returns:
            Typed result instance.
            
        Raises:
            ValueError: If result cannot be extracted or parsed.
        """
        pass


class ResponseHandlerFactory:
    """Factory for creating response handler strategies."""

    _handlers: dict[str, ResponseHandlerStrategy] = {
        "openai": OpenAIResponseHandler(),
        "vllm": VLLMResponseHandler(),
    }

    @classmethod
    def get_handler(cls, provider_name: str) -> ResponseHandlerStrategy:
        """Get the appropriate response handler strategy.
        
        Args:
            provider_name: Name of the provider ('openai', 'vllm', etc.).
            
        Returns:
            ResponseHandlerStrategy instance.
            
        Raises:
            ValueError: If provider is not supported.
        """
        handler = cls._handlers.get(provider_name)
        if handler is None:
            raise ValueError(
                f"No response handler for provider: {provider_name}. "
                f"Supported providers: {list(cls._handlers.keys())}"
            )
        return handler

    @classmethod
    def register_handler(
        cls,
        provider_name: str,
        handler: ResponseHandlerStrategy
    ) -> None:
        """Register a custom response handler strategy.
        
        Args:
            provider_name: Unique identifier for the provider.
            handler: ResponseHandlerStrategy implementation.
        """
        cls._handlers[provider_name] = handler
        logger.info("Registered custom response handler: %s", provider_name)
