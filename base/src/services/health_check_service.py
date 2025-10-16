"""Health-related service helpers for the agent application."""

import logging
import uuid
from typing import Optional

import httpx

from ..config import Config
from ..models.api import ComponentHealth

logger = logging.getLogger(__name__)


class AIProviderHealthChecker:
    """Health check provider for the configured AI model."""

    def __init__(self, config: Config):
        self.config = config
        self.enabled = config.get("health_check_ai_provider", True)

    async def health_check(self) -> ComponentHealth:
        """Check AI provider health if enabled."""
        if not self.enabled:
            logger.debug("AI provider health check is disabled")
            return ComponentHealth(
                status="healthy",
                message="AI provider health check disabled",
            )

        ai_config = self.config.get_ai_config()
        provider = ai_config.get("provider")

        if not provider:
            return ComponentHealth(
                status="healthy",
                message="No AI provider configured",
            )

        if provider == "vllm":
            base_url = ai_config.get("base_url")
            if not base_url:
                return ComponentHealth(
                    status="unhealthy",
                    message="vLLM base_url not configured",
                )

            api_key = ai_config.get("api_key")
            if not api_key:
                return ComponentHealth(
                    status="unhealthy",
                    message="vLLM api_key not configured",
                )

            try:
                headers = {"Authorization": f"Bearer {api_key}"}
                # Suppress httpx INFO logs for health checks
                async with httpx.AsyncClient(
                    event_hooks={"request": [], "response": []}
                ) as client:
                    # vLLM servers have a /health endpoint at the root, not under /v1
                    # Remove /v1 suffix if present
                    health_url = base_url.rstrip("/").removesuffix("/v1") + "/health"
                    response = await client.get(health_url, headers=headers)
                    response.raise_for_status()
                    return ComponentHealth(
                        status="healthy",
                        message=f"vLLM reachable at {base_url}",
                    )
            except httpx.RequestError as e:
                logger.warning("vLLM health check failed: %s", e)
                return ComponentHealth(
                    status="unhealthy",
                    message=f"vLLM check failed: {e}",
                )

        elif provider == "openai":
            # No external dependency to check, assume healthy if configured
            return ComponentHealth(
                status="healthy",
                message="openai provider selected; health assumed",
            )

        return ComponentHealth(
            status="unknown",
            message=f"Unsupported provider: {provider}",
        )


class DaprPubSubHealthChecker:
    """Health check for RabbitMQ connectivity through Dapr pubsub."""

    def __init__(self, config: Config, pubsub_name: Optional[str] = None):
        self.config = config
        self.enabled = config.get("health_check_rabbitmq", True)

        # Get pubsub name from event publishing config if not provided
        if pubsub_name is None:
            event_pub_config = config.get_event_publishing_config()
            pubsub_name = event_pub_config.get("default_pubsub_name", "pubsub")

        self.pubsub_name = pubsub_name
        self.dapr_http_port = config.get("dapr_http_port", 3500)
        self.dapr_base_url = f"http://localhost:{self.dapr_http_port}"

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
            # Suppress httpx INFO logs for health checks
            async with httpx.AsyncClient(
                timeout=5.0, event_hooks={"request": [], "response": []}
            ) as client:
                # Step 1: Check Dapr sidecar health
                try:
                    dapr_health_response = await client.get(
                        f"{self.dapr_base_url}/v1.0/healthz"
                    )
                    dapr_health_response.raise_for_status()
                except httpx.RequestError as e:
                    logger.warning("Dapr sidecar not reachable: %s", e)
                    return ComponentHealth(
                        status="unhealthy",
                        message=f"Dapr sidecar unreachable: {e}",
                    )

                # Step 2: Check if pubsub component is loaded
                try:
                    metadata_response = await client.get(
                        f"{self.dapr_base_url}/v1.0/metadata"
                    )
                    metadata_response.raise_for_status()
                    metadata = metadata_response.json()

                    components = metadata.get("components", [])
                    pubsub_component = next(
                        (c for c in components if c.get("name") == self.pubsub_name),
                        None,
                    )

                    if not pubsub_component:
                        logger.warning(
                            "Pubsub component '%s' not loaded in Dapr", self.pubsub_name
                        )
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
            logger.error(
                "Unexpected error during RabbitMQ health check: %s", e, exc_info=True
            )
            return ComponentHealth(
                status="unhealthy",
                message=f"Health check error: {e}",
            )
