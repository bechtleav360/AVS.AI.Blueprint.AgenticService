"""Event publisher for handling event publication."""

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ...config import Config
from ...models.events import CloudEvent, GenericCloudEvent
from ...models.config import EventPublishingConfig

if TYPE_CHECKING:  # pragma: no cover
    from ...registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)


class _EventPublisher:
    """Publishes events to configured topics."""

    def __init__(self, component_registry: "ComponentRegistry", settings: Config) -> None:
        self._component_registry: ComponentRegistry = component_registry
        self._settings: Config = settings

    async def publish_result_event(self, result_event: GenericCloudEvent) -> None:
        """
        Publish result event if topic mapping exists for the event type.

        Args:
            result_event: The CloudEvent to potentially publish
        """
        try:
            publishing_service = self._component_registry.get_event_publishing_service()
            if not publishing_service:
                logger.debug("No event publishing service registered, skipping publication")
                return

            event_pub_config: EventPublishingConfig = self._settings.get_event_publishing_config()
            topic_mapping: dict[str, Any] = {k: v.model_dump() for k, v in event_pub_config.topic_mapping.items()}

            if result_event.type in topic_mapping:
                topic_config = topic_mapping[result_event.type]
                logger.info(
                    "Publishing result event type '%s' to topic '%s'",
                    result_event.type,
                    topic_config.topic,
                )

                await publishing_service.publish_event(result_event, topic=topic_config.topic)

                logger.debug(
                    "Successfully published result event %s to topic %s",
                    result_event.id,
                    topic_config.topic,
                )
            else:
                logger.debug(
                    "No topic mapping found for event type '%s', skipping publication",
                    result_event.type,
                )

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
            publishing_service = self._component_registry.get_event_publishing_service()
            if not publishing_service:
                logger.debug("No event publishing service registered, skipping handler event publication")
                return

            event_pub_config = self._settings.get_event_publishing_config()
            topic_mapping = event_pub_config.topic_mapping

            if event_type not in topic_mapping:
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

            topic_config = topic_mapping[event_type]

            logger.info(
                "Publishing handler event type '%s' to topic '%s'",
                event_type,
                topic_config.topic,
                extra={
                    "event_type": event_type,
                    "event_id": handler_event.id,
                    "metadata": metadata,
                },
            )

            await publishing_service.publish_event(handler_event, topic=topic_config.topic)

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
