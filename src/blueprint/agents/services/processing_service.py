"""Unified processing service that coordinates handlers and runtimes."""

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from opentelemetry import trace
from pydantic import ValidationError

from ..config import Config
from ..models import ProcessingResult, ProcessingStatus
from ..models.events import GenericCloudEvent, HandlerResult
from .processing._event_publisher import _EventPublisher
from .processing._handler_chain import _HandlerChainProcessor
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
        self._correlation_context = component_registry.get_correlation_context()
        self.name = self.__class__.__name__

    async def process_event(
        self,
        event: GenericCloudEvent,
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
        new_subject: str | None = None,
    ) -> ProcessingResult:
        """
        Process a CloudEvent through the handler chain and optionally through an agent runtime.

        Args:
            event: The CloudEvent to process
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default
            new_subject: New subject for the CloudEvent

        Returns:
            ProcessingResult describing the processing outcome
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

            correlation_token = self._correlation_context.set(getattr(event, "id", None) or request_id)

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

            # Unwrap Dapr-wrapped events if necessary
            event = self._unwrap_dapr_event(event)

            try:
                # Process through handler chain
                handler_result: Any | HandlerResult | list[HandlerResult] | None = await self._handler_chain.process(event, context)

                # Extract handler result components (always normalized list of HandlerResult)
                handler_results: list[HandlerResult] = self._result_builder.extract_handler_result(handler_result)

                # Publish each event that has an event_type
                for result in handler_results:
                    if result.event_type:
                        await self._event_publisher.publish_handler_event(
                            event_type=result.event_type,
                            data=result.data,
                            metadata=result.metadata or {},
                            source_event=event,
                            new_subject=result.subject or new_subject,
                        )

                status = ProcessingStatus.NO_HANDLER_FOUND if handler_result is None else ProcessingStatus.PROCESSED
                result_data = self._result_builder.build_result_data(request_id, handler_results, status)

                logger.debug(
                    "Event processing completed for request %s",
                    request_id,
                    extra={
                        "request_id": request_id,
                        "status": result_data.status.value,
                        "result_count": len(handler_results),
                    },
                )

                return result_data

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
            finally:
                self._correlation_context.reset(correlation_token)

    async def process_rest_request(
        self,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
    ) -> ProcessingResult:
        """
        Process a REST request by converting it to a CloudEvent and processing.

        Args:
            payload: The REST request payload
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default

        Returns:
            ProcessingResult describing the processing outcome
        """
        # Convert REST payload to CloudEvent format
        event = GenericCloudEvent(
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

    def _unwrap_dapr_event(self, event: GenericCloudEvent) -> GenericCloudEvent:
        """
        Unwrap Dapr-wrapped events.

        Dapr sometimes wraps events in a 'com.dapr.event.sent' envelope.
        This method extracts the inner event if present.

        Args:
            event: The CloudEvent that may be wrapped

        Returns:
            The unwrapped CloudEvent, or the original if not wrapped

        Raises:
            RuntimeError: If the inner event is malformed or unsupported
        """
        if event.type == "com.dapr.event.sent":
            logger.warning(
                "Event from topic %s is of type 'com.dapr.event.sent', unwrapping inner event.",
                getattr(event, "topic", "unknown"),
            )
            inner_event = event.data

            if isinstance(inner_event, GenericCloudEvent):
                return inner_event

            if isinstance(inner_event, dict):
                if "type" not in inner_event:
                    logger.error(
                        "Inner Dapr event is missing required 'type' field: %s",
                        inner_event,
                    )
                    raise RuntimeError("Inner Dapr event is missing required 'type' field")

                try:
                    return GenericCloudEvent.model_validate(inner_event)
                except ValidationError as exc:
                    logger.error("Failed to validate inner Dapr event as CloudEvent: %s", exc)
                    raise RuntimeError("Inner Dapr event could not be parsed as CloudEvent") from exc

            logger.error("Unexpected inner event type: %s", type(inner_event))
            raise RuntimeError("Unsupported inner Dapr event payload type")

        return event
