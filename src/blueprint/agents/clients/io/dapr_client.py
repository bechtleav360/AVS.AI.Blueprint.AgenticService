"""Dapr client implementation for eventing."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ...models.api import ComponentHealth
from ...models.events import CloudEvent
from .io_client_base import IOClientBase

logger = logging.getLogger(__name__)

# Suppress httpx and httpcore INFO logs during health checks
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class DaprClient(IOClientBase):
    """Dapr client for publishing CloudEvents via Dapr pub/sub.

    Managed subscription lifecycle
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Dapr subscriptions are declarative: the Dapr sidecar calls
    ``GET /dapr/subscribe`` to discover topics and then pushes matching
    events to ``POST /events/{topic}``.  No programmatic subscribe call to
    the broker is required.

    ``subscribe(topic_callbacks)`` stores the callback mapping for use by
    ``DaprEventing.publish()`` and starts a background retry task that
    pings the sidecar until it responds.  ``subscriptions_ready`` becomes
    ``True`` once the sidecar is confirmed reachable; ``health_check()``
    additionally pings the sidecar on every call so runtime availability is
    always reflected.

    Config keys
    ~~~~~~~~~~~
    ``event_client_max_retries`` (int, default -1): retries after first
    failure; ``-1`` = indefinite, ``0`` = single attempt.
    ``event_client_retry_delay`` (float, default 5.0): seconds between retries.
    """

    def __init__(self) -> None:
        super().__init__()
        self._topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {}
        self._subscriptions_ready: bool = False
        self._subscriptions_managed: bool = False
        self._retry_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def subscriptions_ready(self) -> bool:
        """``True`` once the sidecar was confirmed reachable at startup."""
        return self._subscriptions_ready

    # ------------------------------------------------------------------
    # Managed subscription API
    # ------------------------------------------------------------------

    async def subscribe(self, topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]]) -> None:
        """Store topic→callback mappings and start the background sidecar-ping retry task.

        Returns immediately; sidecar reachability check happens in the background.
        """
        self._topic_callbacks = topic_callbacks
        self._subscriptions_managed = True
        self._subscriptions_ready = False
        self._retry_task = asyncio.ensure_future(self._start_with_retry())
        self._retry_task.add_done_callback(self._on_retry_done)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        """Initialize the HTTP client for Dapr communication."""
        if self._client is not None:
            return
        self._client = httpx.AsyncClient()
        logger.info("Initialized Dapr client at %s", self.config.get("dapr_url", "http://localhost:3500"))

    async def close(self) -> None:
        """Cancel the retry task and close the HTTP client."""
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        topic: str,
        event: CloudEvent[Any],
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

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ComponentHealth:
        """Return healthy only when subscriptions are established and sidecar is reachable."""
        if not self.config.get("health_check_dapr", True):
            logger.debug("Dapr health check is disabled")
            return ComponentHealth(status="healthy", message="Dapr health check disabled")

        if self._subscriptions_managed and not self._subscriptions_ready:
            return ComponentHealth(status="unhealthy", message="subscriptions not yet established")

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

    # ------------------------------------------------------------------
    # Internal — retry loop
    # ------------------------------------------------------------------

    async def _start_with_retry(self) -> None:
        max_retries: int = self.config.get("event_client_max_retries", -1)
        delay: float = float(self.config.get("event_client_retry_delay", 5.0))
        attempt = 0
        while True:
            try:
                await self._connect_and_subscribe()
                self._subscriptions_ready = True
                logger.info("DaprClient connected and sidecar reachable")
                return
            except Exception as e:
                attempt += 1
                self._subscriptions_ready = False
                if max_retries != -1 and attempt > max_retries:
                    raise
                logger.warning("DaprClient attempt %d failed, retrying in %.1fs: %s", attempt, delay, e)
                await asyncio.sleep(delay)

    def _on_retry_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("DaprClient permanently failed after exhausting retries: %s", exc, exc_info=exc)

    async def _connect_and_subscribe(self) -> None:
        """Connect the HTTP client and verify the Dapr sidecar is reachable."""
        await self.connect()
        if self.config.get("health_check_dapr", True):
            dapr_url = self.config.get("dapr_url", "http://localhost:3500")
            client = await self.client
            response = await client.get(f"{dapr_url}/v1.0/healthz")
            response.raise_for_status()
