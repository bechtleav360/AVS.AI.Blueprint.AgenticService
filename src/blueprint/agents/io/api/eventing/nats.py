"""NATS eventing implementation using NATSClient."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ....clients.io.nats_client import NATSClient
from ....models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .event_handling_base import EventHandlingBase

logger = logging.getLogger(__name__)


class NatsEventing(EventHandlingBase):
    """Implements event handling using NATS via NATSClient.

    ``on_startup`` collects the full topic→callback mapping from all registered
    handlers and config, then hands it to ``NATSClient.subscribe()``.  The client
    owns connection, retry, reconnect, and subscription-readiness tracking.
    """

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self._client: NATSClient | None = None

    async def on_startup(self) -> None:
        self._client = self.registry.get_component(NATSClient)

        topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {}
        for handler in self.registry.get_event_handler():
            for topic in handler.get_subscribed_topics():
                if topic and topic not in topic_callbacks:
                    topic_callbacks[topic] = self._make_event_callback(topic)
        for topic in self.config.get_nats_subscription_config():
            if topic and topic not in topic_callbacks:
                topic_callbacks[topic] = self._make_event_callback(topic)

        if topic_callbacks:
            await self._client.subscribe(topic_callbacks)
        else:
            logger.info("NatsEventing: no auto-subscriptions configured")

    async def on_shutdown(self) -> None:
        pass

    def _make_event_callback(self, topic: str) -> Callable[[CloudEvent[Any]], Awaitable[None]]:
        """Return an async callback that routes an incoming event through the handler chain."""

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

        return _process_event

    @RestApiBase.post("/events/{topic}", tags=["nats"])
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Publish a CloudEvent to a NATS topic.

        Args:
            topic: The topic to publish to.
            event: The CloudEvent to publish.

        Returns:
            Success message.
        """
        if not self._client:
            raise RuntimeError("NATS client not initialized")

        await self._client.publish(topic, event)
        return {"message": f"Published event {event.id} to topic {topic}"}
