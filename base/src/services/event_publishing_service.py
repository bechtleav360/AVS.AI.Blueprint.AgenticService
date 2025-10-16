"""Event publishing service for publishing CloudEvents via Dapr pub/sub."""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

import httpx
from opentelemetry import trace

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config

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
    """

    def __init__(self, config: "Config", dapr_http_port: int = 3500) -> None:
        """
        Initialize the event publishing service.

        Args:
            config: Application configuration
            dapr_http_port: Dapr sidecar HTTP port (default: 3500)
        """
        self._config = config
        self._dapr_http_port = dapr_http_port
        self._dapr_base_url = f"http://localhost:{dapr_http_port}"

        # Load event publishing configuration
        pub_config = self._config.get_event_publishing_config()
        self._default_pubsub_name = pub_config["default_pubsub_name"]
        self._topic_mapping = pub_config["topic_mapping"]

        logger.info(
            "EventPublishingService initialized with pubsub '%s' and %d topic mappings",
            self._default_pubsub_name,
            len(self._topic_mapping),
        )

    async def publish_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        event_id: Optional[str] = None,
        source: Optional[str] = None,
        pubsub_name: Optional[str] = None,
        topic: Optional[str] = None,
        routing_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Publish a CloudEvent to a topic via Dapr.

        Args:
            event_type: CloudEvent type (e.g., "agent.output.invoice.processed")
            data: Event data payload
            event_id: Optional CloudEvent ID (auto-generated if not provided)
            source: Optional CloudEvent source (defaults to service name)
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
            span.set_attribute("event.type", event_type)

            # Determine topic and routing key from mapping or explicit parameters
            if topic is None or routing_key is None:
                routing_config = self._config.get_routing_for_event_type(event_type)
                if routing_config is None:
                    error_msg = f"No topic mapping found for event type: {event_type}"
                    logger.error(error_msg)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                    raise ValueError(error_msg)

                # Use config values if not explicitly provided
                if topic is None:
                    topic = routing_config["topic"]
                if routing_key is None:
                    routing_key = routing_config.get("routing_key")

            # Use default pubsub if not specified
            if pubsub_name is None:
                pubsub_name = self._default_pubsub_name

            span.set_attribute("pubsub.name", pubsub_name)
            span.set_attribute("pubsub.topic", topic)
            if routing_key:
                span.set_attribute("pubsub.routing_key", routing_key)

            # Build CloudEvent envelope
            cloud_event = {
                "specversion": "1.0",
                "type": event_type,
                "source": source or f"/agent/{self._config.get('app_name', 'agent')}",
                "id": event_id or self._generate_event_id(),
                "datacontenttype": "application/json",
                "data": data,
            }

            # Publish to Dapr
            publish_url = f"{self._dapr_base_url}/v1.0/publish/{pubsub_name}/{topic}"

            logger.info(
                "Publishing event type '%s' to topic '%s' on pubsub '%s'%s",
                event_type,
                topic,
                pubsub_name,
                f" with routing key '{routing_key}'" if routing_key else "",
                extra={
                    "event_type": event_type,
                    "topic": topic,
                    "pubsub_name": pubsub_name,
                    "routing_key": routing_key,
                    "event_id": cloud_event["id"],
                },
            )

            try:
                # Prepare headers with routing key metadata for Dapr
                headers = {"Content-Type": "application/cloudevents+json"}
                if routing_key:
                    # Dapr metadata for RabbitMQ routing key
                    headers["metadata.routingKey"] = routing_key

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        publish_url,
                        json=cloud_event,
                        headers=headers,
                        timeout=5.0,
                    )
                    response.raise_for_status()

                logger.info(
                    "Successfully published event type '%s' to topic '%s'",
                    event_type,
                    topic,
                    extra={
                        "event_type": event_type,
                        "topic": topic,
                        "event_id": cloud_event["id"],
                    },
                )

                span.set_attribute("publish.status", "success")

                return {
                    "status": "published",
                    "topic": topic,
                    "pubsub_name": pubsub_name,
                    "routing_key": routing_key,
                    "event_id": cloud_event["id"],
                }

            except httpx.HTTPError as e:
                error_msg = f"Failed to publish event: {str(e)}"
                logger.error(
                    "Failed to publish event type '%s' to topic '%s': %s",
                    event_type,
                    topic,
                    str(e),
                    extra={
                        "event_type": event_type,
                        "topic": topic,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                raise

    async def publish_agent_output(
        self,
        output_data: Dict[str, Any],
        event_subtype: str,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method to publish agent output events.

        Args:
            output_data: Agent output data
            event_subtype: Subtype for the event (e.g., "invoice.processed")
            event_id: Optional CloudEvent ID

        Returns:
            Publishing result dictionary
        """
        event_type = f"agent.output.{event_subtype}"
        return await self.publish_event(
            event_type=event_type,
            data=output_data,
            event_id=event_id,
        )

    async def publish_error_event(
        self,
        error_data: Dict[str, Any],
        error_type: str = "processing",
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method to publish error events.

        Args:
            error_data: Error details
            error_type: Type of error (e.g., "processing", "validation")
            event_id: Optional CloudEvent ID

        Returns:
            Publishing result dictionary
        """
        event_type = f"agent.error.{error_type}"
        return await self.publish_event(
            event_type=event_type,
            data=error_data,
            event_id=event_id,
        )

    async def publish_status_event(
        self,
        status_data: Dict[str, Any],
        status: str,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method to publish status events.

        Args:
            status_data: Status details
            status: Status type (e.g., "started", "completed", "failed")
            event_id: Optional CloudEvent ID

        Returns:
            Publishing result dictionary
        """
        event_type = f"agent.status.{status}"
        return await self.publish_event(
            event_type=event_type,
            data=status_data,
            event_id=event_id,
        )

    def _generate_event_id(self) -> str:
        """Generate a unique event ID."""
        from uuid import uuid4

        return str(uuid4())

    def get_topic_for_event_type(self, event_type: str) -> Optional[str]:
        """
        Get the topic name for a specific event type.

        Args:
            event_type: CloudEvent type

        Returns:
            Topic name or None if no mapping exists
        """
        return self._topic_mapping.get(event_type)

    def get_available_event_types(self) -> list[str]:
        """
        Get list of all configured event types.

        Returns:
            List of event type strings
        """
        return list(self._topic_mapping.keys())
