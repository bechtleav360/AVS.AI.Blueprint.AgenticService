"""Dapr client implementation for eventing."""

import json
import logging
from collections.abc import Awaitable, Callable

import httpx

from ...models.api import ComponentHealth
from ...models.events import CloudEvent
from .io_client_base import IOClientBase

logger = logging.getLogger(__name__)

# Suppress httpx and httpcore INFO logs during health checks
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class DaprClient(IOClientBase):
    """Dapr client for publishing CloudEvents via Dapr pub/sub."""

    def _is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        """Initialize the HTTP client for Dapr communication."""
        if self._client is not None:
            return

        self._client = httpx.AsyncClient()
        logger.info("Initialized Dapr client at %s", self.config.get("dapr_url", "http://localhost:3500"))

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def subscribe(self, topic: str, callback: Callable[[CloudEvent], Awaitable[None]]) -> None:
        """Subscribe to a topic.

        Note: Dapr subscriptions are typically configured declaratively,
        not programmatically. This method is a no-op.
        """
        logger.warning("Dapr subscriptions should be configured declaratively, not via client")

    async def publish(
        self,
        topic: str,
        event: CloudEvent,
        routing_key: str | None = None,
        pubsub_name: str | None = None,
    ) -> None:
        """Publish a CloudEvent to a Dapr pub/sub topic."""
        client = await self.client

        dapr_url = self.config.get("dapr_url", "http://localhost:3500")
        effective_pubsub = pubsub_name or self.config.get("dapr_pubsub_name", "pubsub")
        url = f"{dapr_url}/v1.0/publish/{effective_pubsub}/{topic}"
        headers = {"Content-Type": "application/cloudevents+json"}
        if routing_key:
            headers["metadata.routingKey"] = routing_key
        data = json.dumps(dict(event))

        try:
            response = await client.post(url, content=data, headers=headers)
            response.raise_for_status()
            logger.debug("Published event to Dapr topic '%s': %s", topic, event.id)
        except Exception as e:
            logger.error("Failed to publish event to Dapr topic '%s': %s", topic, str(e))
            raise

    async def health_check(self) -> ComponentHealth:
        """Check Dapr sidecar availability."""
        if not self.config.get("health_check_dapr", True):
            logger.debug("Dapr health check is disabled")
            return ComponentHealth(status="healthy", message="Dapr health check disabled")

        dapr_url = self.config.get("dapr_url", "http://localhost:3500")
        try:
            client = await self.client
            dapr_health_response = await client.get(f"{dapr_url}/v1.0/healthz")
            dapr_health_response.raise_for_status()
            return ComponentHealth(
                status="healthy",
                message=f"Dapr sidecar reachable at {dapr_url}",
            )
        except httpx.RequestError as e:
            logger.warning("Dapr sidecar not reachable: %s", e)
            return ComponentHealth(status="unhealthy", message=f"Dapr sidecar unreachable: {e}")
        except Exception as e:
            logger.error("Unexpected error during Dapr health check: %s", e, exc_info=True)
            return ComponentHealth(status="unhealthy", message=f"Health check error: {e}")
