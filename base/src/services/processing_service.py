"""Unified processing service that coordinates handlers and runtimes."""

import logging
from opentelemetry import trace
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import uuid4

from ..config import Config
from ..models.events import CloudEvent, GenericCloudEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ProcessingService:
    """
    Unified service for processing requests through handlers and runtimes.

    This service provides a consistent interface for all API endpoints
    (REST, Events, Dapr) to process requests using the registered handlers
    and agent runtimes.
    """

    def __init__(
        self,
        settings: Config,
        component_registry: "ComponentRegistry",
    ) -> None:
        self._settings = settings
        self._component_registry = component_registry

    async def process_event(
        self,
        event: CloudEvent,
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None,
    ) -> CloudEvent:
        """
        Process a CloudEvent through the handler chain and optionally through an agent runtime.

        Args:
            event: The CloudEvent to process
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default

        Returns:
            A CloudEvent containing the processing result
        """
        if context is None:
            context = {}

        request_id = str(uuid4())
        context["request_id"] = request_id

        with tracer.start_as_current_span("processing_service.process_event") as span:
            span.set_attribute("request_id", request_id)
            span.set_attribute("event.type", event.type)
            span.set_attribute("event.source", event.source)

            if hasattr(event, "id"):
                span.set_attribute("event.id", event.id)

            logger.info(
                "Starting event processing for request %s",
                request_id,
                extra={
                    "request_id": request_id,
                    "event_type": event.type,
                    "event_source": event.source,
                    "event_id": getattr(event, "id", None),
                    "runtime_name": runtime_name,
                },
            )

            try:
                # Process through handler chain
                # Handlers can call agents directly using _get_agent()
                handler_result = await self._process_through_handlers(event, context)

                # Check if result is a Pydantic model with event_type
                event_type_to_publish = None
                result_data_dict = None
                result_metadata = {}

                if handler_result is not None:
                    # Check if it's a Pydantic model with event_type attribute
                    if hasattr(handler_result, "event_type") and hasattr(
                        handler_result, "data"
                    ):
                        event_type_to_publish = handler_result.event_type
                        result_data_dict = handler_result.data
                        if hasattr(handler_result, "metadata"):
                            result_metadata = handler_result.metadata or {}
                    else:
                        # Legacy dict result
                        result_data_dict = handler_result

                # Prepare result data
                status = (
                    "processed" if handler_result is not None else "no_handler_found"
                )

                result_data = {
                    "request_id": request_id,
                    "status": status,
                    "result": result_data_dict,
                    "metadata": result_metadata,
                }

                if handler_result is None:
                    result_data["message"] = "No handler processed this event"

                logger.debug(
                    "Event processing completed for request %s",
                    request_id,
                    extra={
                        "request_id": request_id,
                        "status": status,
                        "has_result": handler_result is not None,
                        "event_type_to_publish": event_type_to_publish,
                    },
                )

                # Publish event if handler specified an event_type
                if event_type_to_publish:
                    await self._publish_handler_event(
                        event_type=event_type_to_publish,
                        data=result_data_dict,
                        metadata=result_metadata,
                        source_event=event,
                    )

                # Create result CloudEvent
                result_event = CloudEvent(
                    specversion="1.0",
                    id=str(uuid4()),
                    source=self._settings.get("app_name", "agent-service"),
                    type=f"agent.output.{event.type}",
                    data=result_data,
                    subject=event.subject,
                )

                # Publish result event if topic mapping exists
                await self._publish_result_event(result_event)

                return result_event

            except Exception as e:
                logger.error(
                    "Event processing failed for request %s: %s",
                    request_id,
                    str(e),
                    extra={"request_id": request_id, "error": str(e)},
                    exc_info=True,
                )
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    async def process_rest_request(
        self,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None,
    ) -> CloudEvent:
        """
        Process a REST request by converting it to a CloudEvent and processing.

        Args:
            payload: The REST request payload
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default

        Returns:
            A CloudEvent containing the processing result
        """
        # Convert REST payload to CloudEvent format
        event = CloudEvent(
            specversion="1.0",
            id=str(uuid4()),
            source="/api/rest",
            type="rest.request",
            data=payload,
        )

        return await self.process_event(event, context, runtime_name)

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a comprehensive health check of the processing service.

        Returns:
            Health check results for handlers and runtimes
        """
        with tracer.start_as_current_span("processing_service.health_check") as span:
            try:
                # Check runtimes
                runtime_health = await self._health_check_runtimes()

                # Check handlers (basic check - they're registered)
                handlers = self._component_registry.get_handlers()
                handler_health = {
                    "status": "healthy" if handlers else "unhealthy",
                    "count": len(handlers),
                    "handlers": [
                        {"name": h.name, "priority": h.priority} for h in handlers
                    ],
                }

                overall_healthy = handler_health["status"] == "healthy" and any(
                    r.get("status") == "healthy" for r in runtime_health.values()
                )

                result = {
                    "status": "healthy" if overall_healthy else "unhealthy",
                    "handlers": handler_health,
                    "runtimes": runtime_health,
                }

                span.set_attribute("health.status", result["status"])
                span.set_attribute("handlers.count", len(handlers))
                span.set_attribute("runtimes.count", len(runtime_health))

                return result

            except Exception as e:
                logger.error("Health check failed: %s", str(e), exc_info=True)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                return {"status": "unhealthy", "error": str(e)}

    # ========================================================================
    # Private Helper Methods (Business Logic)
    # ========================================================================

    async def _process_through_handlers(
        self, event: CloudEvent, context: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Process an event through all registered handlers in priority order.

        Handlers are executed in sequence until one returns a result.
        Handlers can call agents directly using _get_agent_runtime().

        Returns:
            Result from the first handler that returns a non-None value, or None
        """
        handlers = self._component_registry.get_handlers()

        with tracer.start_as_current_span("processing_service.handler_chain") as span:
            span.set_attribute("event.type", event.type)
            span.set_attribute("handlers.count", len(handlers))

            logger.debug(
                "Processing event through %d handlers",
                len(handlers),
                extra={
                    "event_type": event.type,
                    "event_id": getattr(event, "id", None),
                    "handlers_count": len(handlers),
                },
            )

            for handler in handlers:
                try:
                    if await handler.can_handle(event, context):
                        logger.info(
                            "Handler %s can handle event %s",
                            handler.name,
                            event.type,
                            extra={
                                "handler_name": handler.name,
                                "event_type": event.type,
                                "event_id": getattr(event, "id", None),
                            },
                        )

                        result = await handler.handle(event, context)

                        if result is not None:
                            logger.info(
                                "Handler %s processed event %s and returned result",
                                handler.name,
                                event.type,
                                extra={
                                    "handler_name": handler.name,
                                    "event_type": event.type,
                                    "event_id": getattr(event, "id", None),
                                    "has_result": True,
                                },
                            )
                            span.set_attribute("handler.processed_by", handler.name)
                            return result
                        else:
                            logger.info(
                                "Handler %s processed event %s but passed to next handler",
                                handler.name,
                                event.type,
                                extra={
                                    "handler_name": handler.name,
                                    "event_type": event.type,
                                    "event_id": getattr(event, "id", None),
                                    "has_result": False,
                                },
                            )
                            # Continue to next handler

                except Exception as e:
                    logger.error(
                        "Handler %s failed to process event %s: %s",
                        handler.name,
                        event.type,
                        str(e),
                        extra={
                            "handler_name": handler.name,
                            "event_type": event.type,
                            "event_id": getattr(event, "id", None),
                            "error": str(e),
                        },
                        exc_info=True,
                    )
                    span.record_exception(e)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    raise

            logger.warning(
                "No handler processed event %s",
                event.type,
                extra={
                    "event_type": event.type,
                    "event_id": getattr(event, "id", None),
                    "handlers_count": len(handlers),
                },
            )
            return None

    async def _process_with_runtime(
        self, runtime_name: Optional[str] = None, context: Any = None, **kwargs
    ) -> Any:
        """
        Process a request using the specified runtime or default runtime.

        Args:
            runtime_name: Name of the runtime to use, or None for default
            context: Processing context to pass to the runtime
            **kwargs: Additional keyword arguments to pass to the runtime's process_request

        Returns:
            The result from the runtime's process_request method

        Raises:
            ValueError: If no runtime is available or runtime not found
        """
        with tracer.start_as_current_span(
            "processing_service.runtime_execution"
        ) as span:
            runtime = self._component_registry.get_runtime(runtime_name)

            if runtime is None:
                error_msg = f"No runtime available (requested: {runtime_name})"
                logger.error(error_msg)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                raise ValueError(error_msg)

            actual_name = (
                runtime_name or self._component_registry.get_default_runtime_name()
            )
            span.set_attribute("runtime.name", actual_name)

            logger.info(
                "Processing request with runtime %s",
                actual_name,
                extra={
                    "runtime_name": actual_name,
                    "has_context": context is not None,
                    "additional_kwargs": list(kwargs.keys()) if kwargs else [],
                },
            )

            try:
                result = await runtime.process_request(context=context, **kwargs)
                logger.info(
                    "Runtime %s processed request successfully",
                    actual_name,
                    extra={
                        "runtime_name": actual_name,
                        "has_result": result is not None,
                    },
                )
                return result

            except Exception as e:
                logger.error(
                    "Runtime %s failed to process request: %s",
                    actual_name,
                    str(e),
                    extra={"runtime_name": actual_name, "error": str(e)},
                    exc_info=True,
                )
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    async def _publish_result_event(self, result_event: GenericCloudEvent) -> None:
        """
        Publish result event if topic mapping exists for the event type.

        Args:
            result_event: The CloudEvent to potentially publish
        """

        try:
            # Get event publishing service
            publishing_service = self._component_registry.get_event_publishing_service()
            if not publishing_service:
                logger.debug(
                    "No event publishing service registered, skipping publication"
                )
                return

            # Check if there's a topic mapping for this event type
            event_pub_config = self._settings.get_event_publishing_config()
            topic_mapping = event_pub_config.get("topic_mapping", {})

            if result_event.type in topic_mapping:
                topic = topic_mapping[result_event.type]
                logger.info(
                    "Publishing result event type '%s' to topic '%s'",
                    result_event.type,
                    topic,
                )

                await publishing_service.publish_event(result_event, topic=topic)

                logger.debug(
                    "Successfully published result event %s to topic %s",
                    result_event.id,
                    topic,
                )
            else:
                logger.debug(
                    "No topic mapping found for event type '%s', skipping publication",
                    result_event.type,
                )

        except Exception as e:
            # Log but don't fail the request if publishing fails
            logger.warning(
                "Failed to publish result event: %s",
                str(e),
                extra={
                    "event_id": result_event.id,
                    "event_type": result_event.type,
                    "error": str(e),
                },
            )

    async def _publish_handler_event(
        self,
        event_type: str,
        data: Any,
        metadata: Dict[str, Any],
        source_event: CloudEvent,
    ) -> None:
        """
        Publish an event from a handler result.

        This method is called when a handler returns a HandlerResult with an event_type.
        It creates a new CloudEvent and publishes it according to the topic mapping.

        Args:
            event_type: The event type to publish (e.g., 'invoice.validated')
            data: The event data
            metadata: Additional metadata
            source_event: The original event that triggered this processing
        """
        try:
            # Get event publishing service
            publishing_service = self._component_registry.get_event_publishing_service()
            if not publishing_service:
                logger.debug(
                    "No event publishing service registered, skipping handler event publication"
                )
                return

            # Check if there's a topic mapping for this event type
            event_pub_config = self._settings.get_event_publishing_config()
            topic_mapping = event_pub_config.get("topic_mapping", {})

            if event_type not in topic_mapping:
                logger.warning(
                    "No topic mapping found for handler event type '%s', skipping publication",
                    event_type,
                )
                return

            # Create new CloudEvent for the handler result
            handler_event = CloudEvent(
                specversion="1.0",
                id=str(uuid4()),
                source=self._settings.get("app_name", "agent-service"),
                type=event_type,
                data=data,
                subject=source_event.subject,
            )

            # Get topic configuration (can be string or dict with routing_key)
            topic_config = topic_mapping[event_type]

            logger.info(
                "Publishing handler event type '%s' with config: %s",
                event_type,
                topic_config,
                extra={
                    "event_type": event_type,
                    "event_id": handler_event.id,
                    "metadata": metadata,
                },
            )

            await publishing_service.publish_event(handler_event, topic=topic_config)

            logger.info(
                "Successfully published handler event %s (type: %s)",
                handler_event.id,
                event_type,
            )

        except Exception as e:
            # Log but don't fail the request if publishing fails
            logger.warning(
                "Failed to publish handler event: %s",
                str(e),
                extra={
                    "event_type": event_type,
                    "error": str(e),
                    "metadata": metadata,
                },
            )

    async def _health_check_runtimes(self) -> Dict[str, Dict[str, Any]]:
        """Perform health checks on all registered runtimes."""
        with tracer.start_as_current_span("processing_service.runtime_health") as span:
            results = {}
            runtimes = self._component_registry.get_all_runtimes()

            for name, runtime in runtimes.items():
                try:
                    health_result = await runtime.health_check()
                    results[name] = health_result
                    logger.info("Health check passed for runtime %s", name)
                except Exception as e:
                    logger.error("Health check failed for runtime %s: %s", name, str(e))
                    results[name] = {"status": "unhealthy", "error": str(e)}

            span.set_attribute("runtimes.count", len(runtimes))
            span.set_attribute(
                "runtimes.healthy_count",
                sum(1 for r in results.values() if r.get("status") == "healthy"),
            )

            return results
