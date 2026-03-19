"""VLLM client implementation."""

import logging
from typing import Awaitable, Callable, Union, Any

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from .ai_client_base import AIClientBase
from ...models.config import AIConfig
from ...models.api import ComponentHealth
from ...models.events import CloudEvent

logger = logging.getLogger(__name__)


class VLLMClient(AIClientBase):
    """VLLM client for AI model interactions (OpenAI-compatible API).

    The underlying AsyncOpenAI SDK client is initialised synchronously in __init__
    (no real network connection is made at that point). This allows create_model()
    to be called immediately after construction so that AgentRuntime can receive a
    fully-configured model at init time.
    """

    def __init__(self, config: Union[dict[str, Any], AIConfig]) -> None:
        ai_config = config if isinstance(config, AIConfig) else AIConfig(**config)
        super().__init__(ai_config)
        self._model: Model | None = None
        if isinstance(config, dict):
            self._base_url = config.get("vllm_base_url", "http://localhost:8000/v1")
            self._api_key = config.get("vllm_api_key", "not-needed")
            self._model_name = config.get("vllm_model_name", "default-model")
            self._timeout = config.get("vllm_timeout", 60)
        else:
            self._base_url = config.base_url
            self._api_key = config.api_key
            self._model_name = config.model_name
            self._timeout = config.max_tokens if config.max_tokens else 60

        # vLLM-specific profile
        self._vllm_profile = ModelProfile(
            thinking_tags=("<think>", "</think>"),
            ignore_streamed_leading_whitespace=True,
            supports_json_schema_output=True,
            default_structured_output_mode="native",
        )

        # Initialise SDK client synchronously — no actual TCP connection yet
        self._client: AsyncOpenAI = AsyncOpenAI(
            max_retries=3,
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
        )
        logger.info("Initialized VLLM client for model: %s at %s", self._model_name, self._base_url)

    def _is_connected(self) -> bool:
        """AsyncOpenAI is always initialised; connection is deferred to first API call."""
        return self._client is not None

    async def connect(self) -> None:
        """No-op — AsyncOpenAI connects lazily on first API call."""

    async def close(self) -> None:
        """Close the VLLM client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def subscribe(
        self, topic: str, callback: Callable[[CloudEvent], Awaitable[None]]
    ) -> None:
        """Subscribe to a topic - not applicable for VLLM client."""
        logger.warning("VLLM client does not support subscriptions")

    async def publish(self, topic: str, event: CloudEvent, routing_key: str | None = None) -> None:
        """Publish an event - not applicable for VLLM client."""
        logger.warning("VLLM client does not support publishing")

    async def health_check(self) -> ComponentHealth:
        """Check the health of the VLLM client."""
        try:
            client = await self.client
            # Simple health check by attempting to list models
            models = await client.models.list()
            if models.data:
                return ComponentHealth(
                    status="healthy",
                    message=f"VLLM client connected, {len(models.data)} models available",
                )
            else:
                return ComponentHealth(
                    status="unhealthy",
                    message="VLLM client connected but no models available",
                )
        except Exception as e:
            logger.warning("VLLM health check failed: %s", str(e), exc_info=True)
            return ComponentHealth(
                status="unhealthy",
                message=f"VLLM connection error: {str(e)}",
            )

    def create_model(self) -> Model:
        """Create and return a configured VLLM model."""
        if self._model is not None:
            raise RuntimeError("Model already created")
        
        if self._client is None:
            raise RuntimeError("VLLM client not connected")

        provider = OpenAIProvider(openai_client=self._client)

        self._model = OpenAIChatModel(
            provider=provider,
            model_name=self._model_name,
            profile=self._vllm_profile,
        )

        logger.info(
            "VLLM model configured: %s at %s (timeout: %ds, JSON schema enabled)",
            self._model_name,
            self._base_url,
            self._timeout,
        )

        return self._model