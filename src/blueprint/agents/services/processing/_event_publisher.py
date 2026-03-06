"""Event publisher for handling event publication with support for both Dapr and NATS."""

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ...config import Config
from ...models.config import EventPublishingConfig
from ...models.events import CloudEvent, GenericCloudEvent
from ...api.nats_bus import NatsEventBus

if TYPE_CHECKING:  # pragma: no cover
    from ...registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)


class _EventPublisher:
    """Publishes events to configured topics."""

    def __init__(self, component_registry: "ComponentRegistry", settings: Config) -> None:
        self._component_registry: ComponentRegistry = component_registry
        self._settings: Config = settings
        self._event_pub_config: EventPublishingConfig | None = None

    def _get_event_pub_config(self) -> EventPublishingConfig:
        """Get the event publishing configuration."""
        if self._event_pub_config is None:
            self._event_pub_config = self._settings.get_event_publishing_config()
        return self._event_pub_config

    def _should_use_nats(self) -> bool:
        """Determine if NATS should be used based on the event_bus setting."""
        return self._settings.get("event_bus", "").lower() == "nats"

    async def _get_topic_config(self, event_type: str) -> dict[str, Any] | None:
        """Get topic configuration for the given event type."""
        topic_mapping = self._get_event_pub_config().topic_mapping
        if event_type in topic_mapping:
            return topic_mapping[event_type].model_dump()
        return None

    async def _publish_with_nats(self, event: GenericCloudEvent, topic_config: dict[str, Any]) -> None:
        """Publish an event using NATS."""
        try:
            topic = topic_config.get("topic")
            if not topic:
                logger.error("No topic specified in topic config for event type: %s", event.type)
                return

            logger.info(
                "Publishing event type '%s' to NATS topic '%s'",
                event.type,
                topic,
            )

            # Create a new NatsEventBus instance with the component registry and settings
            nats_bus = NatsEventBus(component_registry=self._component_registry, config=self._settings)

            # Connect to NATS
            await nats_bus.connect()

            try:
                # Publish the event
                await nats_bus.publish(topic, event)
                logger.debug("Successfully published event %s to NATS topic %s", event.id, topic)
            finally:
                # Always close the connection
                await nats_bus.close()

        except Exception as e:
            logger.error("Failed to publish event to NATS: %s", str(e), exc_info=True)
            raise

    async def _publish_with_dapr(self, event: GenericCloudEvent, topic_config: dict[str, Any]) -> None:
        """Publish an event using Dapr."""
        try:
            publishing_service = self._component_registry.get_event_publishing_service()
            if not publishing_service:
                logger.debug("No Dapr publishing service registered")
                return

            topic = topic_config.get("topic")
            if not topic:
                logger.error("No topic specified in topic config for event type: %s", event.type)
                return

            logger.info(
                "Publishing event type '%s' to Dapr topic '%s'",
                event.type,
                topic,
            )

            await publishing_service.publish_event(event, topic=topic)
            logger.debug("Successfully published event %s to Dapr topic %s", event.id, topic)

        except Exception as e:
            logger.error("Failed to publish event to Dapr: %s", str(e), exc_info=True)
            raise

    async def publish_result_event(self, result_event: GenericCloudEvent) -> None:
        """
        Publish result event if topic mapping exists for the event type.

        Args:
            result_event: The CloudEvent to potentially publish
        """
        try:
            topic_config = await self._get_topic_config(result_event.type)
            if not topic_config:
                logger.debug(
                    "No topic mapping found for event type '%s', skipping publication",
                    result_event.type,
                )
                return

            if self._should_use_nats():
                await self._publish_with_nats(result_event, topic_config)
            else:
                await self._publish_with_dapr(result_event, topic_config)

        except Exception as e:
            logger.warning(
                "Failed to publish result event: %s",
                str(e),
                extra={
                    "event_id": result_event.id,
                    "event_type": result_event.type,
                    "error": str(e),
                },
            )

    async def publish_handler_event(
        self,
        event_type: str,
        data: Any,
        metadata: dict[str, Any],
        source_event: CloudEvent,
        new_subject: str | None = None,
    ) -> None:
        """
        Publish an event from a handler result.

        Args:
            event_type: The event type to publish
            data: The event data
            metadata: Additional metadata
            source_event: The original event that triggered this processing
            new_subject: Optional new subject for the event
        """

        try:
            topic_config = await self._get_topic_config(event_type)
            if topic_config.get("topic", "unknown") == source_event.topic:
                logger.warning(
                    "Incoming event type '%s' is the same as the source event topic '%s', skipping publication",
                    topic_config.get("topic", "unknown"),
                    source_event.topic,
                )
                return

            if not topic_config:
                logger.warning(
                    "No topic mapping found for handler event type '%s', skipping publication",
                    event_type,
                )
                return

            handler_event = CloudEvent(
                specversion="1.0",
                id=str(uuid4()),
                source=self._settings.get("app_name", "agent-service"),
                type=event_type,
                data=data,
                subject=new_subject or source_event.subject,
            )

            logger.info(
                "Publishing handler event type '%s' to topic '%s'",
                event_type,
                topic_config.get("topic", "unknown"),
                extra={
                    "event_type": event_type,
                    "event_id": handler_event.id,
                    "metadata": metadata,
                },
            )

            if self._should_use_nats():
                await self._publish_with_nats(handler_event, topic_config)
            else:
                await self._publish_with_dapr(handler_event, topic_config)

            logger.info(
                "Successfully published handler event %s (type: %s)",
                handler_event.id,
                event_type,
            )

        except Exception as e:
            logger.warning(
                "Failed to publish handler event: %s",
                str(e),
                extra={
                    "event_type": event_type,
                    "error": str(e),
                    "metadata": metadata,
                },
            )
