"""OpenAI client implementation."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .ai_client_base import AIClientBase
from ...models.api import ComponentHealth
from ...models.events import CloudEvent

logger = logging.getLogger(__name__)


class OpenAIClient(AIClientBase):
    """OpenAI client for AI model interactions."""

    def _is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        """No-op — AsyncOpenAI connects lazily on first API call."""

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def subscribe(self, topic: str, callback: Callable[[CloudEvent[Any]], Awaitable[None]]) -> None:
        logger.warning("OpenAI client does not support subscriptions")

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        logger.warning("OpenAI client does not support publishing")

    def create_model(self) -> Model:
        """Read config and create a configured OpenAI model."""
        if self._model is not None:
            raise RuntimeError("Model already created")

        ai_config = self.config.get_ai_config(self._runtime_name)
        self._client = AsyncOpenAI(max_retries=3, api_key=ai_config.api_key)
        settings = OpenAIResponsesModelSettings(**ai_config.model_settings)  # type: ignore[typeddict-item]
        provider = OpenAIProvider(openai_client=self._client)
        self._model = OpenAIResponsesModel(
            provider=provider,
            model_name=ai_config.model_name,  # type: ignore[arg-type]
            settings=settings,
        )
        logger.info("OpenAI model configured: %s. Additional settings: %s", ai_config.model_name, settings)
        return self._model

    async def health_check(self) -> ComponentHealth:
        """Check the health of the OpenAI client."""
        if self._client is None:
            return ComponentHealth(status="unhealthy", message="OpenAI client not initialized")

        try:
            models = await self._client.models.list()
            if models.data:
                return ComponentHealth(
                    status="healthy",
                    message=f"OpenAI client connected, {len(models.data)} models available",
                )
            return ComponentHealth(status="unhealthy", message="OpenAI client connected but no models available")
        except Exception as e:
            logger.warning("OpenAI health check failed: %s", str(e), exc_info=True)
            return ComponentHealth(status="unhealthy", message=f"OpenAI connection error: {str(e)}")
