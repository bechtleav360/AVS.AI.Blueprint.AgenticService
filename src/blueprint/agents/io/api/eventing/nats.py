"""NATS eventing implementation using NATSClient."""

import logging
from typing import Any

from ....clients.io.nats_client import NATSClient
from ....models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .event_handling_base import EventHandlingBase

logger = logging.getLogger(__name__)


class NatsEventing(EventHandlingBase):
    """Implements event handling using NATS via NATSClient."""

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self._client: NATSClient | None = None

    async def on_startup(self) -> None:
        """Fetch the registered NATSClient and auto-subscribe to declared topics.

        Topics are collected from two sources (handler-declared topics first,
        then config-declared topics). Duplicates are silently dropped — the
        first occurrence wins, so handler declarations take priority.
        """
        self._client = self.registry.get_component(NATSClient)

        seen: dict[str, None] = {}
        for handler in self.registry.get_event_handler():
            for topic in handler.get_subscribed_topics():
                if topic and topic not in seen:
                    seen[topic] = None
        for topic in self.config.get_nats_subscription_config():
            if topic and topic not in seen:
                seen[topic] = None

        if not seen:
            logger.info("NatsEventing: no auto-subscriptions configured")
            return

        for topic in seen:
            await self._subscribe_to_topic(topic)

    async def _subscribe_to_topic(self, topic: str) -> None:
        """Subscribe to a single NATS topic using the standard processing callback.

        Extracted as a method so the closure correctly captures ``topic`` by
        value at call time, avoiding the loop late-binding pitfall.
        """
        if not self._client:
            raise RuntimeError("NATS client not initialized")

        async def _process_event(event: CloudEvent[Any]) -> None:
            try:
                context = {"nats_topic": topic}
                processing_result = await self._process_cloud_event(event, context)
                logger.debug(
                    "Processed CloudEvent %s on topic %s with status %s",
                    event.id,
                    topic,
                    processing_result.status.value,
                )
            except (RetryableHandlerError, InvalidEventError, CriticalHandlerError) as exc:
                logger.error("Event processing failed: %s", str(exc), exc_info=True)

        await self._client.subscribe(topic, _process_event)
        logger.info("NatsEventing: auto-subscribed to topic '%s'", topic)

    async def on_shutdown(self) -> None:
        """No shutdown actions required — NATSClient lifecycle is managed separately."""

    @RestApiBase.post("/nats/subscribe/{topic}", tags=["nats"])
    async def subscribe(self, topic: str, queue_group: str | None = None) -> dict[str, Any]:
        """Subscribe to a NATS topic.

        Args:
            topic: The topic to subscribe to
            queue_group: Optional queue group

        Returns:
            Success message
        """
        if not self._client:
            raise RuntimeError("NATS client not initialized")

        # Callback to process incoming events
        async def _process_event(event: CloudEvent[Any]) -> None:
            try:
                context = {"nats_topic": topic}
                processing_result = await self._process_cloud_event(event, context)
                logger.debug(
                    "Processed CloudEvent %s on topic %s with status %s",
                    event.id,
                    topic,
                    processing_result.status.value,
                )
            except (RetryableHandlerError, InvalidEventError, CriticalHandlerError) as exc:
                logger.error("Event processing failed: %s", str(exc), exc_info=True)
                # NATS handles retries/acks via client

        await self._client.subscribe(topic, _process_event)
        return {"message": f"Subscribed to topic {topic}"}

    @RestApiBase.post("/events/{topic}", tags=["nats"])
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Publish a CloudEvent to a NATS topic.

        Args:
            topic: The topic to publish to
            event: The CloudEvent to publish

        Returns:
            Success message
        """
        if not self._client:
            raise RuntimeError("NATS client not initialized")

        await self._client.publish(topic, event)
        return {"message": f"Published event {event.id} to topic {topic}"}
