"""Abstract base class for AI model clients."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic_ai.models import Model

from ..client_base import ClientBase
from ...models.config import AIConfig


class AIClientBase(ClientBase, ABC):
    """Abstract base for AI model clients.

    Extends ClientBase with the model creation contract required by AgentRuntime.
    All AI provider clients (vLLM, OpenAI, etc.) should inherit from this class.

    AI clients initialise their underlying SDK client synchronously in __init__
    (no real network call is made — the actual TCP connection is deferred to the
    first API call). This allows create_model() to be called immediately after
    construction, which is required because AgentRuntime (a pydantic_ai.Agent
    subclass) needs a fully-configured model at init time.

    on_startup() is a no-op for AI clients; on_shutdown() closes the SDK client.
    """

    def __init__(self, config: AIConfig) -> None:
        """Initialize the AI client.

        Args:
            config: AI provider configuration. Reading from this object in __init__
                    is allowed — it is not Component._config.
        """
        super().__init__()
        self._ai_config = config

    @abstractmethod
    def create_model(self) -> Model:
        """Create and return a configured pydantic_ai Model instance.

        Returns:
            Configured Model instance ready for use with AgentRuntime
        """
        raise NotImplementedError
