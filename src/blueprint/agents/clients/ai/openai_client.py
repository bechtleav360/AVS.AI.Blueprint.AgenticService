"""OpenAI client implementation."""

import logging
from typing import Any, Awaitable, Callable, Union

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .ai_client_base import AIClientBase
from ...models.config import AIConfig
from ...models.api import ComponentHealth
from ...models.events import CloudEvent

logger = logging.getLogger(__name__)


class OpenAIClient(AIClientBase):
    """OpenAI client for AI model interactions.

    The underlying AsyncOpenAI SDK client is initialised synchronously in __init__
    (no real network connection is made at that point). This allows create_model()
    to be called immediately after construction so that AgentRuntime can receive a
    fully-configured model at init time.
    """

    def __init__(self, config: Union[dict[str, Any], AIConfig]) -> None:
        ai_config = config if isinstance(config, AIConfig) else AIConfig(**config)
        super().__init__(ai_config)
        if isinstance(config, dict):
            self._model_name = config.get("model_name", "gpt-4o-mini")
            self._api_key = config.get("api_key", "")
            self._model_settings = OpenAIResponsesModelSettings(**config.get("model_settings", {}))
        else:
            self._model_name = config.model_name
            self._api_key = config.api_key
            self._model_settings = OpenAIResponsesModelSettings(**config.model_settings)
        # Initialise SDK client synchronously — no actual TCP connection yet
        self._client: AsyncOpenAI = AsyncOpenAI(max_retries=3, api_key=self._api_key)
        self._model: Model | None = None
        logger.info("Initialized OpenAI client for model: %s", self._model_name)

    def _is_connected(self) -> bool:
        """AsyncOpenAI is always initialised; connection is deferred to first API call."""
        return self._client is not None

    async def connect(self) -> None:
        """No-op — AsyncOpenAI connects lazily on first API call."""

    async def close(self) -> None:
        """Close the OpenAI client."""

        if self._client is not None:
            await self._client.close()
            self._client = None

    async def subscribe(
        self, topic: str, callback: Callable[[CloudEvent], Awaitable[None]]
    ) -> None:
        """Subscribe to a topic - not applicable for OpenAI client."""

        logger.warning("OpenAI client does not support subscriptions")

    async def publish(self, topic: str, event: CloudEvent, routing_key: str | None = None) -> None:
        """Publish an event - not applicable for OpenAI client."""

        logger.warning("OpenAI client does not support publishing")

    async def health_check(self) -> ComponentHealth:
        """Check the health of the OpenAI client."""

        try:
            client = await self.client
            # Simple health check by attempting to list models
            models = await client.models.list()
            if models.data:
                return ComponentHealth(
                    status="healthy",
                    message=f"OpenAI client connected, {len(models.data)} models available",
                )
            else:
                return ComponentHealth(
                    status="unhealthy",
                    message="OpenAI client connected but no models available",
                )
        except Exception as e:
            logger.warning("OpenAI health check failed: %s", str(e), exc_info=True)
            return ComponentHealth(
                status="unhealthy",
                message=f"OpenAI connection error: {str(e)}",
            )

    def create_model(self) -> Model:
        """Create and return a configured OpenAI model."""
        if self._model is not None:
            raise RuntimeError("Model already created")
        
        if self._client is None:
            raise RuntimeError("OpenAI client not connected")

        provider = OpenAIProvider(openai_client=self._client)
        self._model = OpenAIResponsesModel(provider=provider, model_name=self._model_name, settings=self._model_settings)
        logger.info("OpenAI model configured: %s. Additional settings: %s", self._model_name, self._model_settings)

        return self._model