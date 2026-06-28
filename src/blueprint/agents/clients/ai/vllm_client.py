"""VLLM client implementation."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from .ai_client_base import AIClientBase
from ...models.api import ComponentHealth
from ...models.events import CloudEvent

logger = logging.getLogger(__name__)

_VLLM_PROFILE = ModelProfile(
    thinking_tags=("<think>", "</think>"),
    ignore_streamed_leading_whitespace=True,
    supports_json_schema_output=True,
    default_structured_output_mode="native",
)


class VLLMClient(AIClientBase):
    """VLLM client for AI model interactions (OpenAI-compatible API)."""

    def _is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        """No-op — AsyncOpenAI connects lazily on first API call."""

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def subscribe(self, topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]]) -> None:
        logger.warning("VLLM client does not support subscriptions")

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        logger.warning("VLLM client does not support publishing")

    def create_model(self) -> Model:
        """Read config and create a configured VLLM model."""
        if self._model is not None:
            raise RuntimeError("Model already created")

        ai_config = self.config.get_ai_config(self._runtime_name)
        self._client = AsyncOpenAI(
            max_retries=3,
            base_url=ai_config.base_url,
            api_key=ai_config.api_key,
            timeout=ai_config.max_tokens if ai_config.max_tokens else 60,
        )
        provider = OpenAIProvider(openai_client=self._client)
        self._model = OpenAIChatModel(
            provider=provider,
            model_name=ai_config.model_name,  # type: ignore[arg-type]
            profile=_VLLM_PROFILE,
        )
        logger.info("VLLM model configured: %s at %s", ai_config.model_name, ai_config.base_url)
        return self._model

    async def health_check(self) -> ComponentHealth:
        """Check the health of the VLLM client."""
        if self._client is None:
            return ComponentHealth(status="unhealthy", message="VLLM client not initialized")

        try:
            models = await self._client.models.list()
            if models.data:
                return ComponentHealth(
                    status="healthy",
                    message=f"VLLM client connected, {len(models.data)} models available",
                )
            return ComponentHealth(status="unhealthy", message="VLLM client connected but no models available")
        except Exception as e:
            logger.warning("VLLM health check failed: %s", str(e), exc_info=True)
            return ComponentHealth(status="unhealthy", message=f"VLLM connection error: {str(e)}")
