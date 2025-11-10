"""Unified processing service that coordinates handlers and runtimes."""

import logging
from opentelemetry import trace
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import uuid4

from ..config import Config
from ..models.events import CloudEvent, GenericCloudEvent
from .processing._handler_chain import _HandlerChainProcessor
from .processing._event_publisher import _EventPublisher
from .processing._health_checker import _HealthChecker
from .processing._result_builder import _ResultBuilder

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
        self._handler_chain = _HandlerChainProcessor(component_registry)
        self._event_publisher = _EventPublisher(component_registry, settings)
        self._health_checker = _HealthChecker(component_registry)
        self._result_builder = _ResultBuilder()

    async def process_event(
        self,
        event: CloudEvent,
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None,
        new_subject: Optional[str] = None,
    ) -> CloudEvent:
        """
        Process a CloudEvent through the handler chain and optionally through an agent runtime.

        Args:
            event: The CloudEvent to process
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default
            new_subject: New subject for the CloudEvent

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
                handler_result = await self._handler_chain.process(event, context)

                # Extract handler result components
                event_type_to_publish, result_data_dict, result_metadata = (
                    self._result_builder.extract_handler_result(handler_result)
                )

                # Build result data
                result_data = self._result_builder.build_result_data(
                    request_id, result_data_dict, event_type_to_publish
                )

                logger.debug(
                    "Event processing completed for request %s",
                    request_id,
                    extra={
                        "request_id": request_id,
                        "status": result_data["status"],
                        "has_result": handler_result is not None,
                        "event_type_to_publish": event_type_to_publish,
                    },
                )

                # Publish handler event if specified
                if event_type_to_publish:
                    await self._event_publisher.publish_handler_event(
                        event_type=event_type_to_publish,
                        data=result_data_dict,
                        metadata=result_metadata,
                        source_event=event,
                        new_subject=new_subject,
                    )

                # Create and publish result CloudEvent
                result_event = CloudEvent(
                    specversion="1.0",
                    id=str(uuid4()),
                    source=self._settings.get("app_name", "agent-service"),
                    type=f"agent.output.{event.type}",
                    data=result_data,
                    subject=new_subject or event.subject,
                )

                await self._event_publisher.publish_result_event(result_event)

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
                runtime_health = await self._health_checker.check_runtimes()
                handler_health = self._health_checker.check_handlers()

                overall_healthy = handler_health["status"] == "healthy" and any(
                    r.get("status") == "healthy" for r in runtime_health.values()
                )

                result = {
                    "status": "healthy" if overall_healthy else "unhealthy",
                    "handlers": handler_health,
                    "runtimes": runtime_health,
                }

                span.set_attribute("health.status", result["status"])
                span.set_attribute("handlers.count", handler_health["count"])
                span.set_attribute("runtimes.count", len(runtime_health))

                return result

            except Exception as e:
                logger.error("Health check failed: %s", str(e), exc_info=True)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                return {"status": "unhealthy", "error": str(e)}


    async def _process_with_runtime(self, runtime_name: Optional[str] = None, context: Any = None, **kwargs) -> Any:
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
        with tracer.start_as_current_span("processing_service.runtime_execution") as span:
            runtime = self._component_registry.get_runtime(runtime_name)

            if runtime is None:
                error_msg = f"No runtime available (requested: {runtime_name})"
                logger.error(error_msg)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                raise ValueError(error_msg)

            actual_name = runtime_name or self._component_registry.get_default_runtime_name()
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

