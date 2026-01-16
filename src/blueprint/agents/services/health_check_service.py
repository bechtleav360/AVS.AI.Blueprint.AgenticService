"""Health-related service helpers for the agent application."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

import httpx

from ..config import Config
from ..models.api import ComponentHealth
from ..models.config import AIConfig

logger = logging.getLogger(__name__)

# Suppress httpx and httpcore INFO logs during health checks
# These loggers emit HTTP request/response details that clutter logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class AIProviderHealthChecker:
    """Health check provider for the configured AI model."""

    def __init__(self, config: Config, runtime_names: Iterable[str] | None = None) -> None:
        self.config: Config = config
        self.enabled: bool = config.get("health_check_ai_provider", True)
        self._runtime_names = self._normalize_runtime_names(runtime_names)

    @staticmethod
    def _normalize_runtime_names(runtime_names: Iterable[str] | None) -> list[str]:
        names: list[str] = []
        if runtime_names:
            for name in runtime_names:
                normalized = (name or "default").strip() or "default"
                if normalized not in names:
                    names.append(normalized)
        if not names:
            return ["default"]
        return names

    async def health_check(self) -> ComponentHealth:
        """Check AI provider health if enabled."""
        if not self.enabled:
            logger.debug("AI provider health check is disabled")
            return ComponentHealth(
                status="healthy",
                message="AI provider health check disabled",
            )

        unhealthy_messages: list[str] = []
        healthy_runtimes: list[str] = []
        any_provider = False

        for runtime_name in self._runtime_names:
            ai_config: AIConfig = self.config.get_ai_config(runtime_name)
            provider: str | None = ai_config.provider

            if not provider:
                continue

            any_provider = True

            if provider == "vllm":
                runtime_result = await self._check_vllm_runtime(runtime_name, ai_config)
                if runtime_result.status == "healthy":
                    healthy_runtimes.append(runtime_result.message or f"[{runtime_name}] vLLM healthy")
                else:
                    unhealthy_messages.append(runtime_result.message or f"[{runtime_name}] vLLM check failed")
                    logger.warning(
                        "AI provider health check failed for runtime '%s': %s",
                        runtime_name,
                        runtime_result.message,
                    )
            elif provider == "openai":
                healthy_runtimes.append(f"[{runtime_name}] OpenAI configured")
            else:
                message = f"[{runtime_name}] Unsupported provider: {provider}"
                unhealthy_messages.append(message)
                logger.warning(message)

        if unhealthy_messages:
            return ComponentHealth(
                status="unhealthy",
                message="; ".join(unhealthy_messages),
            )

        if not any_provider:
            return ComponentHealth(
                status="healthy",
                message="No AI provider configured",
            )

        if not healthy_runtimes:
            return ComponentHealth(
                status="healthy",
                message="AI provider configured",
            )

        return ComponentHealth(
            status="healthy",
            message="AI runtimes healthy: " + ", ".join(healthy_runtimes),
        )

    async def _check_vllm_runtime(self, runtime_name: str, ai_config: AIConfig) -> ComponentHealth:
        base_url: str | None = ai_config.base_url
        if not base_url:
            return ComponentHealth(
                status="unhealthy",
                message=f"[{runtime_name}] vLLM base_url not configured",
            )

        api_key: str | None = ai_config.api_key
        if not api_key:
            return ComponentHealth(
                status="unhealthy",
                message=f"[{runtime_name}] vLLM api_key not configured",
            )

        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient() as client:
                # vLLM servers have a /health endpoint at the root, not under /v1
                # Remove /v1 suffix if present
                health_url = base_url.rstrip("/").removesuffix("/v1") + "/health"
                response = await client.get(health_url, headers=headers)
                response.raise_for_status()
                # Only log successful health checks at debug level
                logger.debug("vLLM health check passed for runtime '%s': %s", runtime_name, base_url)
                return ComponentHealth(
                    status="healthy",
                    message=f"[{runtime_name}] vLLM reachable at {base_url}",
                )
        except httpx.RequestError as e:
            # Log failures at warning level
            logger.warning("vLLM health check failed for runtime '%s': %s", runtime_name, e)
            return ComponentHealth(
                status="unhealthy",
                message=f"[{runtime_name}] vLLM check failed: {e}",
            )


class DaprPubSubHealthChecker:
    """Health check for RabbitMQ connectivity through Dapr pubsub."""

    def __init__(self, config: Config, pubsub_name: str | None = None) -> None:
        self.config: Config = config
        self.enabled: bool = config.get("health_check_rabbitmq", True)

        # Get pubsub name from event publishing config if not provided
        if pubsub_name is None:
            event_pub_config = self.config.get_event_publishing_config()
            pubsub_name = event_pub_config.default_pubsub_name

        self.pubsub_name: str = pubsub_name
        self.dapr_http_port: int = config.get("dapr_http_port", 3500)
        self.dapr_base_url: str = f"http://localhost:{self.dapr_http_port}"

    async def health_check(self) -> ComponentHealth:
        """Check RabbitMQ connectivity through Dapr pubsub.

        This verifies:
        1. Dapr sidecar is reachable
        2. RabbitMQ pubsub component is loaded
        3. Can publish to a health check topic
        """
        if not self.enabled:
            logger.debug("RabbitMQ health check is disabled")
            return ComponentHealth(
                status="healthy",
                message="RabbitMQ health check disabled",
            )

        # Check if RabbitMQ is configured
        rabbitmq_host = self.config.get("rabbitmq_host")
        if not rabbitmq_host:
            return ComponentHealth(
                status="healthy",
                message="RabbitMQ not configured",
            )

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Step 1: Check Dapr sidecar health
                try:
                    dapr_health_response = await client.get(f"{self.dapr_base_url}/v1.0/healthz")
                    dapr_health_response.raise_for_status()
                except httpx.RequestError as e:
                    logger.warning("Dapr sidecar not reachable: %s", e)
                    return ComponentHealth(
                        status="unhealthy",
                        message=f"Dapr sidecar unreachable: {e}",
                    )

                # Step 2: Check if pubsub component is loaded
                try:
                    metadata_response = await client.get(f"{self.dapr_base_url}/v1.0/metadata")
                    metadata_response.raise_for_status()
                    metadata = metadata_response.json()

                    components = metadata.get("components", [])
                    pubsub_component = next(
                        (c for c in components if c.get("name") == self.pubsub_name),
                        None,
                    )

                    if not pubsub_component:
                        logger.warning("Pubsub component '%s' not loaded in Dapr", self.pubsub_name)
                        return ComponentHealth(
                            status="unhealthy",
                            message=f"Pubsub component '{self.pubsub_name}' not loaded in Dapr",
                        )

                except httpx.RequestError as e:
                    logger.warning("Failed to query Dapr metadata: %s", e)
                    return ComponentHealth(
                        status="unhealthy",
                        message=f"Dapr metadata check failed: {e}",
                    )

                # Step 3: Test publish capability (lightweight health check message)
                try:
                    health_topic = "health.check"
                    health_message = {
                        "check_id": str(uuid.uuid4()),
                        "timestamp": "health_check",
                    }

                    publish_response = await client.post(
                        f"{self.dapr_base_url}/v1.0/publish/{self.pubsub_name}/{health_topic}",
                        json=health_message,
                    )
                    publish_response.raise_for_status()

                    return ComponentHealth(
                        status="healthy",
                        message=f"RabbitMQ reachable via Dapr pubsub '{self.pubsub_name}'",
                    )

                except httpx.RequestError as e:
                    logger.warning("Failed to publish health check message: %s", e)
                    return ComponentHealth(
                        status="unhealthy",
                        message=f"RabbitMQ publish failed: {e}",
                    )

        except Exception as e:
            logger.error("Unexpected error during RabbitMQ health check: %s", e, exc_info=True)
            return ComponentHealth(
                status="unhealthy",
                message=f"Health check error: {e}",
            )
