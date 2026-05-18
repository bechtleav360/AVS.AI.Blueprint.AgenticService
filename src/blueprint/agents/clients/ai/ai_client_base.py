"""Abstract base class for AI model clients."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic_ai.models import Model

from ..client_base import ClientBase


class AIClientBase(ClientBase, ABC):
    """Abstract base for AI model clients.

    Extends ClientBase with the model creation contract required by AgentRuntime.
    All AI provider clients (vLLM, OpenAI, etc.) should inherit from this class.

    AI clients are Components: they read their configuration via self.config using
    the runtime_name passed at construction. create_model() must be called after
    AppBuilder.build() has injected the shared config.

    on_startup() is a no-op; on_shutdown() closes the SDK client.
    """

    def __init__(self, runtime_name: str) -> None:
        super().__init__()
        self._runtime_name = runtime_name
        self._model: Model | None = None
        # Use runtime_name as the component name so health checks and registry
        # lookups use a meaningful identifier. Rename immediately after the
        # base __init__ has registered with the class-derived name.
        self.name = f"{runtime_name}_ai_client"

    @abstractmethod
    def create_model(self) -> Model:
        """Read config and create a configured pydantic_ai Model instance."""
        raise NotImplementedError
