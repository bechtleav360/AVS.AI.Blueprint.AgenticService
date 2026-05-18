"""Event publishing service for publishing CloudEvents via a configured eventing client."""

import logging
from typing import Any
from uuid import uuid4

from opentelemetry import trace

from ...component.component import traced
from ..service_base import ServiceBase
from ...clients.io.io_client_base import IOClientBase
from ...models import GenericCloudEvent
from ...models.config import EventPublishingConfig
from ...models.events import CloudEvent

logger = logging.getLogger(__name__)


class EventPublishingService(ServiceBase):
    """Service for publishing CloudEvents to topics via a configured eventing client.

    Uses IOClientBase for transport-agnostic publishing (Dapr, NATS, etc.).
    Topic-to-event-type mapping is resolved from application configuration.
    The active IO client is resolved from the registry in on_startup().
    """

    def __init__(self) -> None:
        super().__init__()
        self._client: IOClientBase | None = None
        self._pub_config: EventPublishingConfig | None = None

    async def on_startup(self) -> None:
        """Resolve IO client from registry and load event publishing configuration."""
        self._client = self.registry.get_component(IOClientBase)
        self._pub_config = self.config.get_event_publishing_config()

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    def _get_pub_config(self) -> EventPublishingConfig:
        """Get the event publishing configuration (set during on_startup)."""
        if self._pub_config is None:
            raise RuntimeError("EventPublishingService has not been started — call on_startup() first")
        return self._pub_config

    @traced("event")
    async def publish_event(
        self,
        event: GenericCloudEvent,
        topic: str | None = None,
        routing_key: str | None = None,
        pubsub_name: str | None = None,
    ) -> dict[str, Any]:
        """Publish a CloudEvent to a topic via the configured client.

        Args:
            event: The CloudEvent to publish
            topic: Optional explicit topic name (uses event-type mapping if not provided)
            routing_key: Optional routing key (e.g. for RabbitMQ via Dapr)
            pubsub_name: Optional pubsub component name (client-specific, passed through)

        Returns:
            Dictionary with publishing result

        Raises:
            ValueError: If no topic mapping exists for the event type and no topic given
        """
        pub_config = self._get_pub_config()

        if topic is None or routing_key is None:
            routing_config = pub_config.topic_mapping.get(event.type)
            if routing_config is None and topic is None:
                error_msg = f"No topic mapping found for event type: {event.type}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            if routing_config is not None:
                if topic is None:
                    topic = routing_config.topic
                if routing_key is None:
                    routing_key = routing_config.routing_key

        event.source = event.source or f"/agent/{self.config.get('app_name', 'agent')}"
        event.id = event.id or str(uuid4())
        event.datacontenttype = event.datacontenttype or "application/json"

        span = trace.get_current_span()
        span.set_attribute("pubsub.topic", topic or "")
        if routing_key:
            span.set_attribute("pubsub.routing_key", routing_key)

        logger.info("Publishing event type '%s' to topic '%s'", event.type, topic)
        await self._client.publish(topic, event, routing_key=routing_key)  # type: ignore[union-attr, arg-type]

        trace.get_current_span().set_attribute("publish.status", "success")
        logger.info("Successfully published event type '%s' to topic '%s'", event.type, topic)

        return {"status": "published", "topic": topic, "routing_key": routing_key, "event_id": event.id}

    async def publish_handler_event(
        self,
        event_type: str,
        data: Any,
        metadata: dict[str, Any],
        source_event: CloudEvent[Any],
        new_subject: str | None = None,
    ) -> None:
        """Construct and publish a CloudEvent from a handler result.

        Args:
            event_type: The event type to publish
            data: The event data
            metadata: Additional metadata (used for logging)
            source_event: The original event that triggered this processing
            new_subject: Optional subject override
        """
        try:
            pub_config = self._get_pub_config()
            topic_config = pub_config.topic_mapping.get(event_type)

            if not topic_config:
                logger.warning(
                    "No topic mapping found for handler event type '%s', skipping publication",
                    event_type,
                )
                return

            if topic_config.topic == getattr(source_event, "topic", None):
                logger.warning(
                    "Handler event topic '%s' matches source event topic, skipping publication to prevent loop",
                    topic_config.topic,
                )
                return

            handler_event = GenericCloudEvent(
                specversion="1.0",
                id=str(uuid4()),
                source=self.config.get("app_name", "agent-service"),
                type=event_type,
                data=data,
                subject=new_subject or getattr(source_event, "subject", None),
            )

            logger.info(
                "Publishing handler event type '%s' to topic '%s'",
                event_type,
                topic_config.topic,
                extra={"event_type": event_type, "event_id": handler_event.id, "metadata": metadata},
            )

            await self.publish_event(handler_event)

        except Exception as e:
            logger.warning(
                "Failed to publish handler event: %s",
                str(e),
                extra={"event_type": event_type, "error": str(e), "metadata": metadata},
            )

    async def publish_status_event(self, status_data: dict[str, Any], status: str, event_id: str | None = "") -> dict[str, Any]:
        """Convenience method to publish status events.

        Args:
            status_data: Status details
            status: Status type (e.g., "started", "completed", "failed")
            event_id: Optional CloudEvent ID

        Returns:
            Publishing result dictionary
        """
        event = GenericCloudEvent(type=f"agent.status.{status}", data=status_data, id=event_id)
        return await self.publish_event(event)

    def get_topic_for_event_type(self, event_type: str) -> str | None:
        """Get the topic name for a specific event type.

        Args:
            event_type: CloudEvent type

        Returns:
            Topic name or None if no mapping exists
        """
        routing_config = self._get_pub_config().topic_mapping.get(event_type)
        return routing_config.topic if routing_config else None

    def get_available_event_types(self) -> list[str]:
        """Get list of all configured event types.

        Returns:
            List of event type strings
        """
        return list(self._get_pub_config().topic_mapping.keys())
