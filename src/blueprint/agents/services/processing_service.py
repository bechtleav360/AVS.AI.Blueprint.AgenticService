"""Unified processing service that coordinates handlers and runtimes."""

import logging
from opentelemetry import trace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..config import Config
from ..models.events import CloudEvent
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

    Implements the ComponentInterface:
    - name: str - Component name
    - get_registry() -> ComponentRegistry - Access component registry
    - on_startup() - Optional initialization
    - on_shutdown() - Optional cleanup
    """

    def __init__(
        self,
        settings: Config,
        component_registry: "ComponentRegistry",
    ) -> None:
        self._settings: Config = settings
        self._component_registry: ComponentRegistry = component_registry
        self._handler_chain: _HandlerChainProcessor = _HandlerChainProcessor(component_registry)
        self._event_publisher: _EventPublisher = _EventPublisher(component_registry, settings)
        self._health_checker: _HealthChecker = _HealthChecker(component_registry)
        self._result_builder: _ResultBuilder = _ResultBuilder()
        self.name = self.__class__.__name__

    def get_registry(self) -> "ComponentRegistry":
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if self._component_registry is None:
            raise RuntimeError(f"Component registry not wired to service '{self.name}'")
        return self._component_registry

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

    async def process_event(
        self,
        event: CloudEvent,
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
        new_subject: str | None = None,
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
                extracted = self._result_builder.extract_handler_result(handler_result)

                # Check if we have multiple results (list of tuples) or single result
                if isinstance(extracted[0], list):
                    # Multiple results case
                    results_list = extracted[0]

                    logger.debug(
                        "Event processing completed for request %s with %d results",
                        request_id,
                        len(results_list),
                        extra={
                            "request_id": request_id,
                            "result_count": len(results_list),
                            "has_result": handler_result is not None,
                        },
                    )

                    # Publish each handler event that has an event_type
                    for event_type_to_publish, result_data_dict, result_metadata in results_list:
                        if event_type_to_publish:
                            await self._event_publisher.publish_handler_event(
                                event_type=event_type_to_publish,
                                data=result_data_dict,
                                metadata=result_metadata,
                                source_event=event,
                                new_subject=new_subject,
                            )

                    # Build result data with all results
                    result_data = self._result_builder.build_result_data(
                        request_id, [item[1] for item in results_list], "multiple_results"  # Extract just the data
                    )
                else:
                    # Single result case
                    event_type_to_publish, result_data_dict, result_metadata = extracted

                    # Build result data
                    result_data = self._result_builder.build_result_data(request_id, result_data_dict, event_type_to_publish)

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
                    datacontenttype="application/json",
                    dataschema=None,
                    data_base64=None,
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
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
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
            datacontenttype="application/json",
            dataschema=None,
            data_base64=None,
            id=str(uuid4()),
            source="/api/rest",
            type="rest.request",
            data=payload,
            subject="rest.request",
        )

        return await self.process_event(event, context, runtime_name)
