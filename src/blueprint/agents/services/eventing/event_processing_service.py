"""Unified processing service that coordinates handlers and runtimes."""

import logging
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from pydantic import ValidationError

from ...component.component import traced
from ...handler.handler_chain import HandlerChain
from ...models import ProcessingResult, ProcessingStatus
from ...models.events import GenericCloudEvent, HandlerResult
from ..service_base import ServiceBase
from .event_publishing_service import EventPublishingService

logger = logging.getLogger(__name__)


class EventProcessingService(ServiceBase):
    """Unified service for processing requests through handlers and runtimes.

    This service provides a consistent interface for all API endpoints
    (REST, Events, Dapr) to process requests using the registered handlers
    and agent runtimes.
    """

    def __init__(self) -> None:
        super().__init__()
        self._handler_chain: HandlerChain = HandlerChain()
        self._correlation_context = self.registry.correlation_context

    async def on_startup(self) -> None:
        """No startup actions required."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    @traced("event")
    async def process_event(
        self,
        event: GenericCloudEvent,
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
        new_subject: str | None = None,
    ) -> ProcessingResult:
        """Process a CloudEvent through the handler chain.

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
        trace.get_current_span().set_attribute("request_id", request_id)

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

        event = self._unwrap_dapr_event(event)

        try:
            handler_result: Any | HandlerResult | list[HandlerResult] | None = await self._handler_chain.process(event, context)

            handler_results: list[HandlerResult] = self._extract_handler_results(handler_result)

            for result in handler_results:
                if result.event_type:
                    await self.registry.get_component(EventPublishingService).publish_handler_event(
                        event_type=result.event_type,
                        data=result.data,
                        metadata=result.metadata or {},
                        source_event=event,
                        new_subject=result.subject or new_subject,
                    )

            status = ProcessingStatus.NO_HANDLER_FOUND if handler_result is None else ProcessingStatus.PROCESSED
            return self._build_result(request_id, handler_results, status)

        except Exception as e:
            logger.error(
                "Event processing failed for request %s: %s",
                request_id,
                str(e),
                extra={"request_id": request_id, "error": str(e)},
                exc_info=True,
            )
            raise
        finally:
            self._correlation_context.reset(correlation_token)

    async def process_rest_request(
        self,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
    ) -> ProcessingResult:
        """Process a REST request by converting it to a CloudEvent and processing.

        Args:
            payload: The REST request payload
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default

        Returns:
            ProcessingResult describing the processing outcome
        """
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_handler_results(handler_result: Any) -> list[HandlerResult]:
        """Normalize handler output to a list of HandlerResult objects."""

        def _to_handler_result(value: Any) -> HandlerResult:
            if isinstance(value, HandlerResult):
                return value
            if isinstance(value, dict):
                event_type = value.get("event_type") or None
                raw_metadata = value.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                data = value.get("data")
                if not isinstance(data, dict):
                    if event_type is None and not metadata:
                        data = value
                    else:
                        data = {"value": data}
                return HandlerResult(event_type=event_type, data=data, metadata=metadata)
            return HandlerResult(event_type=None, data=value, metadata={})

        if handler_result is None:
            return []
        if isinstance(handler_result, list):
            return [_to_handler_result(item) for item in handler_result]
        return [_to_handler_result(handler_result)]

    @staticmethod
    def _build_result(
        request_id: str,
        handler_results: list[HandlerResult],
        status: ProcessingStatus,
    ) -> ProcessingResult:
        """Build a ProcessingResult from handler outputs."""
        message = "No handler processed this event" if status == ProcessingStatus.NO_HANDLER_FOUND else "Message acknowledged"
        return ProcessingResult(
            request_id=request_id,
            status=status,
            result=handler_results,
            metadata={},
            message=message,
        )

    def _unwrap_dapr_event(self, event: GenericCloudEvent) -> GenericCloudEvent:
        """Unwrap Dapr-wrapped events (com.dapr.event.sent envelope)."""
        if event.type != "com.dapr.event.sent":
            return event

        logger.warning(
            "Event from topic %s is of type 'com.dapr.event.sent', unwrapping inner event.",
            getattr(event, "topic", "unknown"),
        )
        inner_event = event.data

        if isinstance(inner_event, GenericCloudEvent):
            return inner_event

        if isinstance(inner_event, dict):
            if "type" not in inner_event:
                logger.error("Inner Dapr event is missing required 'type' field: %s", inner_event)
                raise RuntimeError("Inner Dapr event is missing required 'type' field")
            try:
                return GenericCloudEvent.model_validate(inner_event)
            except ValidationError as exc:
                logger.error("Failed to validate inner Dapr event as CloudEvent: %s", exc)
                raise RuntimeError("Inner Dapr event could not be parsed as CloudEvent") from exc

        logger.error("Unexpected inner event type: %s", type(inner_event))
        raise RuntimeError("Unsupported inner Dapr event payload type")
