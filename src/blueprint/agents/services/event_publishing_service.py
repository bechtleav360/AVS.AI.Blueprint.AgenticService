"""Event publishing service for publishing CloudEvents via Dapr pub/sub."""

import logging
from typing import Any
from uuid import uuid4

import httpx
from opentelemetry import trace

from ..config import Config
from ..models import GenericCloudEvent
from ..models.config import EventPublishingConfig, TopicConfig

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class EventPublishingService:
    """
    Service for publishing CloudEvents to topics via Dapr pub/sub.

    This service handles:
    - Publishing events to Dapr pub/sub component
    - Mapping event types to topics based on configuration
    - Error handling and retries
    - Observability (logging and tracing)

    Implements the ComponentInterface:
    - name: str - Component name
    - get_registry() -> ComponentRegistry - Access component registry
    - on_startup() - Optional initialization
    - on_shutdown() - Optional cleanup
    """

    def __init__(self, config: Config) -> None:
        """
        Initialize the event publishing service.

        Args:
            config: Application configuration used to derive publishing settings
        """
        self.config: Config = config
        self._dapr_http_port: int = self.config.get("dapr_http_port", 3500)
        self._dapr_base_url: str = f"http://localhost:{self._dapr_http_port}"
        self.name = self.__class__.__name__
        self._registry: Any = None

        # Load event publishing configuration
        self._pub_config: EventPublishingConfig = self.config.get_event_publishing_config()
        self._default_pubsub_name: str = self._pub_config.default_pubsub_name
        self._topic_mapping: dict[str, TopicConfig] = self._pub_config.topic_mapping

    def get_registry(self) -> Any:
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if self._registry is None:
            raise RuntimeError(f"Component registry not wired to service '{self.name}'")
        return self._registry

    def with_registry(self, registry: Any) -> "EventPublishingService":
        """Wire the component registry into this service.

        Args:
            registry: The ComponentRegistry instance

        Returns:
            Self for chaining
        """
        self._registry = registry
        return self

    async def on_startup(self) -> None:
        """Called when service is registered and wired.

        Override to perform initialization tasks.
        """
        pass

    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks.
        """
        pass

    async def publish_event(
        self, event: GenericCloudEvent, pubsub_name: str | None = None, topic: str | None = None, routing_key: str | None = None
    ) -> dict[str, Any]:
        """
        Publish a CloudEvent to a topic via Dapr.

        Args:
            event: The CloudEvent to publish
            pubsub_name: Optional pubsub component name (uses default if not provided)
            topic: Optional explicit topic name (uses mapping if not provided)
            routing_key: Optional routing key for topic-based routing (e.g., RabbitMQ)

        Returns:
            Dictionary with publishing result:
            - status: "published" or "failed"
            - topic: The topic the event was published to
            - pubsub_name: The pubsub component used
            - routing_key: The routing key used (if any)
            - error: Error message if failed

        Raises:
            ValueError: If no topic mapping exists for the event type
            httpx.HTTPError: If Dapr publishing fails
        """

        with tracer.start_as_current_span("event_publishing.publish") as span:
            span.set_attribute("event.type", event.type)

            # Determine topic and routing key from mapping or explicit parameters
            if topic is None or routing_key is None:
                routing_config = self._topic_mapping.get(event.type)
                if routing_config is None:
                    if topic is None:
                        error_msg = f"No topic mapping found for event type: {event.type}"
                        logger.error(error_msg)
                        span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                        raise ValueError(error_msg)
                else:
                    # Use config values if not explicitly provided
                    if topic is None:
                        topic = routing_config.topic
                    if routing_key is None:
                        routing_key = routing_config.routing_key

            # Use default pubsub if not specified
            if pubsub_name is None:
                pubsub_name = self._default_pubsub_name

            span.set_attribute("pubsub.name", pubsub_name)
            span.set_attribute("pubsub.topic", topic)
            if routing_key:
                span.set_attribute("pubsub.routing_key", routing_key)

            # Add default source, if not already set
            event.source = event.source or f"/agent/{self.config.get('app_name', 'agent')}"
            # Generate event ID if not provided by the event data
            event.id = event.id or str(uuid4())
            # Set default datacontenttype if not already set
            event.datacontenttype = event.datacontenttype or "application/json"

            # Publish to Dapr
            publish_url = f"{self._dapr_base_url}/v1.0/publish/{pubsub_name}/{topic}"

            logger.info(
                "Publishing event type '%s' to topic '%s' on pubsub '%s'%s",
                event.type,
                topic,
                pubsub_name,
                f" with routing key '{routing_key}'" if routing_key else "",
                extra={
                    "event_type": event.type,
                    "topic": topic,
                    "pubsub_name": pubsub_name,
                    "routing_key": routing_key,
                    "event_id": event.id,
                },
            )

            try:
                # Prepare headers with routing key metadata for Dapr
                headers = {"Content-Type": "application/cloudevents+json"}
                if routing_key:
                    # Dapr metadata for RabbitMQ routing key
                    headers["metadata.routingKey"] = routing_key

                async with httpx.AsyncClient() as client:
                    response = await client.post(publish_url, json=event.model_dump(), headers=headers, timeout=5.0)
                    response.raise_for_status()

                logger.info(
                    "Successfully published event type '%s' to topic '%s'",
                    event.type,
                    topic,
                    extra={"event_type": event.type, "topic": topic, "event_id": event.id},
                )

                span.set_attribute("publish.status", "success")

                return {"status": "published", "topic": topic, "pubsub_name": pubsub_name, "routing_key": routing_key, "event_id": event.id}

            except httpx.HTTPError as e:
                error_msg = f"Failed to publish event: {str(e)}"
                logger.error(
                    "Failed to publish event type '%s' to topic '%s': %s",
                    event.type,
                    topic,
                    str(e),
                    extra={"event_type": event.type, "topic": topic, "error": str(e)},
                    exc_info=True,
                )
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                raise

    async def publish_status_event(self, status_data: dict[str, Any], status: str, event_id: str | None = "") -> dict[str, Any]:
        """
        Convenience method to publish status events.

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
        """
        Get the topic name for a specific event type.

        Args:
            event_type: CloudEvent type

        Returns:
            Topic name or None if no mapping exists
        """

        routing_config = self._topic_mapping.get(event_type)
        return routing_config.topic if routing_config else None

    def get_available_event_types(self) -> list[str]:
        """
        Get list of all configured event types.

        Returns:
            List of event type strings
        """

        return list(self._topic_mapping.keys())
