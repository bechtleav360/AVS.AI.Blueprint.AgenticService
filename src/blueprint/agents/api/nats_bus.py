"""NATS event bus implementation for the agent service (framework-level)."""

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

import nats
from nats.aio.client import Client as NatsClient
from nats.aio.client import Subscription
from nats.js.client import JetStreamContext
from opentelemetry import trace

from ...agents.models import ProcessingResult, ProcessingStatus
from ..config import Config
from ..models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ..models.events import CloudEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class NatsEventBus:
    """Implements event handling using NATS as the message broker."""

    def __init__(self, component_registry: "ComponentRegistry", config: Config) -> None:
        """Initialize the NATS event bus.

        Args:
            component_registry: The component registry to get processing service from
            config: Configuration object containing NATS settings
        """
        self._component_registry = component_registry
        self._correlation_context = component_registry.get_correlation_context()
        self._nats_client: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._use_jetstream = config.get("nats_use_jetstream", False)
        self._subscriptions: list[Any] = []
        self.required_cloud_event_fields = {"specversion", "id", "source", "type"}
        self._config = config

    async def connect(self) -> None:
        """Connect to NATS server."""
        if self._nats_client is not None and not self._nats_client.is_closed:
            return

        nats_url = self._config.get("nats_url", "nats://localhost:4222")
        max_reconnect_attempts = self._config.get("nats_max_reconnect_attempts", 5)
        reconnect_time_wait = self._config.get("nats_reconnect_time_wait", 2)

        try:
            self._nats_client = await nats.connect(
                nats_url,
                max_reconnect_attempts=max_reconnect_attempts,
                reconnect_time_wait=reconnect_time_wait,
                connect_timeout=10,
                error_cb=self._on_nats_error,
                closed_cb=self._on_nats_connection_closed,
                reconnected_cb=self._on_nats_reconnected,
            )
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
            # Unsubscribe from all subscriptions
            for sub in self._subscriptions:
                await sub.unsubscribe()
            self._subscriptions.clear()

            # Close the connection
            await self._nats_client.close()
            self._nats_client = None
            self._js = None

    async def subscribe(self, topic: str, queue_group: str | None = None) -> None:
        """Subscribe to a topic with an optional queue group.

        Args:
            topic: The topic to subscribe to
            queue_group: Optional queue group for load balancing

        Raises:
            RuntimeError: If NATS client is not connected or subscription fails
        """
        if self._nats_client is None:
            raise RuntimeError("NATS client not connected")

        async def message_handler(msg: Any) -> None:
            """Handle incoming NATS messages."""
            try:
                # Check if this is a JetStream message
                is_jetstream = hasattr(msg, "_jsm")
                await self._handle_nats_message(topic, msg, is_jetstream)
            except Exception as e:
                logger.error("Error processing message on topic %s: %s", topic, str(e), exc_info=True)
                # Don't acknowledge on error to allow for redelivery in JetStream mode

        try:
            if self._use_jetstream and self._js:
                # JetStream subscription
                stream_name = self._config.get("nats_stream_name", "EVENTS")
                durable_name = self._config.get("nats_durable_name", f"{topic}-durable")

                try:
                    # Try to create the stream if it doesn't exist
                    await self._js.add_stream(name=stream_name, subjects=[f"{topic}.>"])
                except Exception as e:
                    if "stream name already in use" not in str(e).lower():
                        logger.warning("Could not create stream: %s", str(e))

                # Subscribe with JetStream
                sub: Subscription = await self._js.subscribe(
                    topic, queue=queue_group, durable=durable_name, manual_ack=True, cb=message_handler
                )
                logger.info("Subscribed to JetStream topic '%s'%s", topic, f" in queue group '{queue_group}'" if queue_group else "")
            else:
                # Core NATS subscription
                sub = await self._nats_client.subscribe(topic, queue=queue_group or "", cb=message_handler)
                logger.info("Subscribed to Core NATS topic '%s'%s", topic, f" in queue group '{queue_group}'" if queue_group else "")

            self._subscriptions.append(sub)

        except Exception as e:
            logger.error("Failed to subscribe to topic '%s': %s", topic, str(e))
            raise

    async def publish(self, topic: str, event: CloudEvent[Any]) -> None:
        """Publish an event to a topic.

        Args:
            topic: The topic to publish to
            event: The CloudEvent to publish

        Raises:
            RuntimeError: If NATS client is not connected or publishing fails
        """
        if self._nats_client is None:
            raise RuntimeError("NATS client not connected")

        try:
            # Convert CloudEvent to bytes for NATS
            event_data = json.dumps(dict(event)).encode()

            if self._use_jetstream and self._js:
                # Publish with JetStream for persistence
                ack = await self._js.publish(topic, event_data)
                logger.debug("Published event to JetStream topic '%s' (seq: %d): %s", topic, ack.seq, event.id)
            else:
                # Publish with Core NATS
                await self._nats_client.publish(topic, event_data)
                logger.debug("Published event to Core NATS topic '%s': %s", topic, event.id)

        except Exception as e:
            logger.error("Failed to publish event to topic '%s': %s", topic, str(e))
            raise

    async def _handle_nats_message(self, topic: str, msg: Any, is_jetstream: bool = False) -> None:
        """Process an incoming NATS message.

        Args:
            topic: The topic the message was received on
            msg: The NATS message
            is_jetstream: Whether this is a JetStream message (affects acknowledgment)
        """
        with tracer.start_as_current_span("nats.handle_message") as span:
            span.set_attribute("nats.topic", topic)
            correlation_token = None

            try:
                # Parse the CloudEvent
                try:
                    event_data = json.loads(msg.data.decode())
                    cloud_event: CloudEvent[Any] = CloudEvent(**event_data)
                    cloud_event.topic = topic
                except Exception as e:
                    logger.error("Failed to parse CloudEvent: %s", str(e))
                    return

                original_event_type = cloud_event.type
                correlation_token = self._correlation_context.set(getattr(cloud_event, "id", None))

                # Handle nested CloudEvents (similar to Dapr unwrapping)
                cloud_event, was_unwrapped = self._unwrap_nested_cloud_event(cloud_event)
                if was_unwrapped:
                    self._correlation_context.reset(correlation_token)
                    correlation_token = self._correlation_context.set(getattr(cloud_event, "id", None))

                context = {
                    "nats_topic": topic,
                    "nats_original_event_type": original_event_type,
                    "nats_inner_event_type": cloud_event.type,
                }

                span.set_attribute("nats.original_event_type", original_event_type)
                if was_unwrapped:
                    logger.debug(
                        "Unwrapped nested CloudEvent of type %s from NATS message",
                        cloud_event.type,
                    )
                    context["nats_unwrapped"] = "true"
                    span.set_attribute("nats.unwrapped", True)
                    span.set_attribute("nats.inner_event_type", cloud_event.type or "")

                # Process through the unified service
                processing_service = self._component_registry.get_processing_service()
                try:
                    processing_result = await processing_service.process_event(cloud_event, context)

                except RetryableHandlerError as exc:
                    logger.error(
                        "Retrying message for topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    # NATS will automatically redeliver unacknowledged messages
                    return

                except InvalidEventError as exc:
                    logger.error(
                        "Dropping message for topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    # Acknowledge to prevent redelivery for JetStream messages
                    if is_jetstream and hasattr(msg, "ack"):
                        await msg.ack()
                    return

                except CriticalHandlerError as exc:
                    logger.error(
                        "Critical error for topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    # Let NATS handle retries
                    return

                except Exception as exc:
                    logger.error(
                        "Processing service failed for NATS topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    # Let NATS handle retries
                    return

                if not isinstance(processing_result, ProcessingResult):
                    logger.error(
                        "Processing service returned unexpected result type %s",
                        type(processing_result),
                    )
                    return

                # Acknowledge successful processing for JetStream messages
                if is_jetstream and hasattr(msg, "_jsm"):
                    try:
                        # Only attempt to ack if the message has an ack method
                        if callable(getattr(msg, "ack", None)):
                            await msg.ack()
                    except Exception as ack_error:
                        logger.error("Failed to acknowledge JetStream message: %s", str(ack_error))

            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                logger.error("NATS message handling failed: %s", str(e), exc_info=True)
            finally:
                self._correlation_context.reset(correlation_token)

    def _unwrap_nested_cloud_event(self, event: CloudEvent[Any]) -> tuple[CloudEvent[Any], bool]:
        """Handle nested CloudEvents if needed."""
        # This is a simplified version of the Dapr unwrapping logic
        # Modify as needed based on your event wrapping requirements
        return event, False

    async def _on_nats_error(self, e: Any) -> None:
        """Handle NATS error events."""
        logger.error("NATS error: %s", str(e))

    async def _on_nats_reconnected(self) -> None:
        """Handle NATS reconnection events."""
        logger.info("Reconnected to NATS server")

    async def _on_nats_connection_closed(self) -> None:
        """Handle NATS connection closed events."""
        logger.warning("Connection to NATS server closed")


if __name__ == "__main__":
    import asyncio
    import uuid
    from typing import Any

    from ..models.events import CloudEvent
    from ..registry.component_registry import ComponentRegistry

    class DummyRegistry(ComponentRegistry):
        def __init__(self, config: dict[str, Any] | None = None) -> None:
            self.config = config or {}

        def get_processing_service(self) -> Any:
            # Return a simple processing service that just logs the event
            class DummyProcessingService:
                async def process_event(self, event: Any, context: dict[str, Any]) -> ProcessingResult:
                    print(f"\nProcessing event: {event.id}")
                    print(f"Context: {context}")
                    return ProcessingResult(
                        request_id=str(uuid.uuid4()), status=ProcessingStatus.PROCESSED, message="Processed successfully"
                    )

            return DummyProcessingService()

        def get_correlation_context(self) -> Any:
            class DummyContext:
                def set(self, correlation_id: str | None) -> str | None:
                    return None

                def reset(self, token: str | None) -> None:
                    pass

            return DummyContext()

        def get_topic_for_event_type(self, event_type: str) -> str:
            # Map event types to topics
            topic_map = {
                "test.event": "test.topic",
                # Add more mappings as needed
            }
            return topic_map.get(event_type, f"events.{event_type}")

    async def send_cloud_event() -> None:
        """Send a test CloudEvent to NATS."""
        config = {"nats_url": "nats://localhost:4222", "nats_max_reconnect_attempts": 3, "nats_reconnect_time_wait": 1}

        # Initialize NATS client with dummy registry
        nats_bus = NatsEventBus(DummyRegistry(config), Config())

        try:
            # Connect to NATS
            print("Connecting to NATS...")
            await nats_bus.connect()

            if not nats_bus._nats_client or nats_bus._nats_client.is_closed:
                raise Exception("Failed to connect to NATS")

            print("Connected to NATS server")

            # Create a test event
            test_event: CloudEvent[Any] = CloudEvent(
                id=str(uuid.uuid4()), source="test.source", type="ai_decomposition_result_v1", data={"message": "Hello, NATS!"}
            )

            # Publish the event
            print(f"\nPublishing test event: {test_event.id}")
            print(f"Type: {test_event.type}")
            print(f"Source: {test_event.source}")
            print(f"Data: {test_event.data}")

            # Publish using the NatsEventBus interface
            await nats_bus.publish("test.topic", test_event)
            print("\nEvent published successfully!")

        except Exception as e:
            print(f"\nError: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
        finally:
            print("\nCleaning up...")
            if nats_bus._nats_client and not nats_bus._nats_client.is_closed:
                await nats_bus.close()
                print("Disconnected from NATS server")

    # Run the example
    asyncio.run(send_cloud_event())
