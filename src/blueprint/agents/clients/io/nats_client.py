"""NATS client implementation for eventing."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import nats
from nats.aio.client import Client as NatsClient
from nats.js.client import JetStreamContext

from ...models.api import ComponentHealth
from ...models.events import CloudEvent
from .io_client_base import IOClientBase

logger = logging.getLogger(__name__)


class NATSClient(IOClientBase):
    """NATS client for subscribing to and publishing CloudEvents.

    Managed subscription lifecycle
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Call ``subscribe(topic_callbacks)`` once at startup with the full
    ``{topic: callback}`` mapping.  The client fires a background retry
    task that connects to the broker and subscribes to every topic.
    ``subscriptions_ready`` becomes ``True`` once all subscriptions are
    active; ``health_check()`` reflects this state so the readiness probe
    keeps the pod out of service rotation until then.

    On disconnect the NATS library fires ``_on_disconnected``, which clears
    the ready flag.  On reconnect ``_on_reconnected`` re-subscribes (JetStream
    only — Core NATS re-subscribes automatically) and restores the flag.

    Config keys
    ~~~~~~~~~~~
    ``event_client_max_retries`` (int, default -1): retries after first failure;
    ``-1`` = indefinite, ``0`` = single attempt.
    ``event_client_retry_delay`` (float, default 5.0): seconds between retries.
    """

    def __init__(self) -> None:
        super().__init__()
        self._nats_client: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._use_jetstream: bool = False
        self._subscriptions: list[Any] = []
        self._topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {}
        self._subscriptions_ready: bool = False
        self._subscriptions_managed: bool = False
        self._retry_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def subscriptions_ready(self) -> bool:
        """``True`` once all managed subscriptions are active."""
        return self._subscriptions_ready

    # ------------------------------------------------------------------
    # Managed subscription API
    # ------------------------------------------------------------------

    async def subscribe(self, topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]]) -> None:
        """Register all topic→callback mappings and start the background retry task.

        Returns immediately; connection and subscription happen in the background.
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
        return self._nats_client is not None and not self._nats_client.is_closed and self._nats_client.is_connected

    async def connect(self) -> None:
        """Connect to the NATS server, registering disconnect/reconnect callbacks."""
        if self._nats_client is not None and not self._nats_client.is_closed:
            return

        nats_url = self.config.get("nats_url", "nats://localhost:4222")
        try:
            self._nats_client = await nats.connect(
                nats_url,
                max_reconnect_attempts=self.config.get("nats_max_reconnect_attempts", 5),
                reconnect_time_wait=self.config.get("nats_reconnect_time_wait", 2),
                connect_timeout=10,
                disconnected_cb=self._on_disconnected,
                reconnected_cb=self._on_reconnected,
            )
            self._client = self._nats_client
            self._use_jetstream = self.config.get("nats_use_jetstream", False)
            if self._use_jetstream:
                try:
                    self._js = self._nats_client.jetstream()
                    logger.info("Connected to NATS server with JetStream at %s", nats_url)
                except Exception as e:
                    logger.warning("JetStream initialization failed, falling back to Core NATS: %s", str(e))
                    self._use_jetstream = False

            if not self._use_jetstream:
                logger.info("Connected to NATS server (Core NATS) at %s", nats_url)
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", str(e))
            raise

    async def close(self) -> None:
        """Cancel the retry task, unsubscribe all topics, and close the connection."""
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task

        if self._nats_client is not None:
            for sub in self._subscriptions:
                with contextlib.suppress(Exception):
                    await sub.unsubscribe()
            self._subscriptions.clear()

            await self._nats_client.close()
            self._nats_client = None
            self._js = None
            self._client = None

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        """Publish a CloudEvent to a topic.

        Args:
            topic: The topic, used for event routing.
            event: The CloudEvent to publish.
            routing_key: Ignored — NATS does not use routing keys.
        """
        client = await self.client

        try:
            event_data = json.dumps(dict(event)).encode()

            if self._use_jetstream and client.jetstream():
                ack = await client.jetstream().publish(topic, event_data)
                logger.debug("Published event to JetStream topic '%s' (seq: %d): %s", topic, ack.seq, event.id)
            else:
                await client.publish(topic, event_data)
                logger.debug("Published event to Core NATS topic '%s': %s", topic, event.id)

        except Exception as e:
            logger.error("Failed to publish event to topic '%s': %s", topic, str(e))
            raise

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ComponentHealth:
        """Return healthy only when connected and all managed subscriptions are active."""
        if not self._is_connected():
            return ComponentHealth(status="unhealthy", message="NATS client not connected")
        if self._subscriptions_managed and not self._subscriptions_ready:
            return ComponentHealth(status="unhealthy", message="connected but subscriptions not yet established")
        server_info = self._nats_client.connected_url  # type: ignore[union-attr]
        sub_info = f" ({len(self._subscriptions)} subscriptions active)" if self._subscriptions else ""
        return ComponentHealth(status="healthy", message=f"Connected to NATS server at {server_info}{sub_info}")

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
                logger.info("NATSClient connected and subscribed successfully")
                return
            except Exception as e:
                attempt += 1
                self._subscriptions_ready = False
                if max_retries != -1 and attempt > max_retries:
                    raise
                logger.warning("NATSClient attempt %d failed, retrying in %.1fs: %s", attempt, delay, e)
                await asyncio.sleep(delay)

    def _on_retry_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("NATSClient permanently failed to connect after exhausting retries: %s", exc, exc_info=exc)

    async def _connect_and_subscribe(self) -> None:
        await self.connect()
        # Clean up any partial subscriptions from a previous failed attempt
        for sub in self._subscriptions:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        self._subscriptions.clear()
        for topic, callback in self._topic_callbacks.items():
            await self._subscribe_one(topic, callback)

    # ------------------------------------------------------------------
    # Internal — per-topic subscription
    # ------------------------------------------------------------------

    async def _subscribe_one(self, topic: str, callback: Callable[[CloudEvent[Any]], Awaitable[None]]) -> None:
        client = await self.client

        async def message_handler(msg: Any) -> None:
            try:
                event_data = json.loads(msg.data.decode())
                cloud_event: CloudEvent[Any] = CloudEvent(**event_data)
                await callback(cloud_event)
            except Exception as ex:
                logger.error("Failed to handle NATS message: %s", str(ex))

        try:
            if self._use_jetstream and client.jetstream():
                stream_name = self.config.get("nats_stream_name", "EVENTS")
                durable_name = self.config.get("nats_durable_name", f"{topic}-durable")

                try:
                    await client.jetstream().add_stream(name=stream_name, subjects=[f"{topic}.>"])
                except Exception as e:
                    if "stream name already in use" not in str(e).lower():
                        logger.warning("Could not create stream: %s", str(e))

                sub = await client.jetstream().subscribe(
                    topic,
                    durable=durable_name,
                    manual_ack=True,
                    cb=message_handler,
                )
                logger.info("Subscribed to JetStream topic '%s'", topic)
            else:
                sub = await client.subscribe(topic, cb=message_handler)
                logger.info("Subscribed to Core NATS topic '%s'", topic)

            self._subscriptions.append(sub)

        except Exception as e:
            logger.error("Failed to subscribe to topic '%s': %s", topic, str(e))
            raise

    # ------------------------------------------------------------------
    # Internal — reconnect callbacks
    # ------------------------------------------------------------------

    async def _on_disconnected(self) -> None:
        self._subscriptions_ready = False
        logger.warning("NATSClient disconnected")

    async def _on_reconnected(self) -> None:
        logger.info("NATSClient reconnected")
        if not self._subscriptions_managed:
            return
        if self._use_jetstream and self._topic_callbacks:
            # JetStream durable consumers do not survive reconnects; re-subscribe manually.
            # Core NATS re-subscribes automatically via the client library.
            self._subscriptions.clear()
            try:
                for topic, callback in self._topic_callbacks.items():
                    await self._subscribe_one(topic, callback)
            except Exception as e:
                logger.error("NATSClient failed to re-establish JetStream subscriptions after reconnect: %s", e)
                return
        self._subscriptions_ready = True
        logger.info("NATSClient subscriptions ready after reconnect")
