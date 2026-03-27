"""NATS client implementation for eventing."""

import json
import logging
from typing import Any
from collections.abc import Awaitable, Callable

import nats
from nats.aio.client import Client as NatsClient
from nats.js.client import JetStreamContext

from ...models.api import ComponentHealth
from ...models.events import CloudEvent
from .io_client_base import IOClientBase

logger = logging.getLogger(__name__)


class NATSClient(IOClientBase):
    """NATS client for subscribing to and publishing CloudEvents."""

    def __init__(self) -> None:
        super().__init__()
        self._nats_client: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._use_jetstream: bool = False
        self._subscriptions: list[Any] = []

    def _is_connected(self) -> bool:
        return self._nats_client is not None and not self._nats_client.is_closed and self._nats_client.is_connected

    async def connect(self) -> None:
        """Connect to NATS server."""
        if self._nats_client is not None and not self._nats_client.is_closed:
            return

        nats_url = self.config.get("nats_url", "nats://localhost:4222")
        try:
            self._nats_client = await nats.connect(
                nats_url,
                max_reconnect_attempts=self.config.get("nats_max_reconnect_attempts", 5),
                reconnect_time_wait=self.config.get("nats_reconnect_time_wait", 2),
                connect_timeout=10,
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
        """Close NATS connection and clean up resources."""
        if self._nats_client is not None:
            for sub in self._subscriptions:
                await sub.unsubscribe()
            self._subscriptions.clear()

            await self._nats_client.close()
            self._nats_client = None
            self._js = None
            self._client = None

    async def subscribe(self, topic: str, callback: Callable[[CloudEvent[Any]], Awaitable[None]]) -> None:
        """Subscribe to a topic and call callback with parsed CloudEvents."""
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

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        """Publish a CloudEvent to a topic.

        Args:
            topic: The topic, used for event routing.
            event: The CloudEvent to publish.
            routing_key: Ignored — NATS does not use routing keys
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

    async def health_check(self) -> ComponentHealth:
        """Check the health of the NATS connection."""
        if self._nats_client and not self._nats_client.is_closed and self._nats_client.is_connected:
            server_info = self._nats_client.connected_url
            return ComponentHealth(status="healthy", message=f"Connected to NATS server at {server_info}")
        else:
            return ComponentHealth(status="unhealthy", message="NATS client not connected")
