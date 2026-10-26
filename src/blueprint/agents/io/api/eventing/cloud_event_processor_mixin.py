"""CloudEvent processing mixin providing dispatch, unwrapping, and correlation and trace context management."""

from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.context import Context

from ....models import ProcessingResult
from ....models.events import CloudEvent
from ....services.eventing.event_processing_service import EventProcessingService

logger = logging.getLogger(__name__)

# The CloudEvents distributed-tracing extension: the W3C trace context the producer published under.
TRACE_CONTEXT_ATTRIBUTES = ("traceparent", "tracestate")


def producer_trace_context(*events: CloudEvent[Any]) -> Context | None:
    """The trace context the first of ``events`` carrying a valid ``traceparent`` was published under.

    The attributes are CloudEvent extensions, so they arrive in ``model_extra``. Only string values
    are offered to the propagator: an empty ``traceparent`` -- what a producer writes when no span
    was current -- or one that does not parse is skipped, so the next event is tried.

    Args:
        events: The candidates, most specific first -- the delivered event before its Dapr envelope.

    Returns:
        The extracted context, or ``None`` if no event carries a usable one.
    """
    for event in events:
        extensions = event.model_extra or {}
        carrier = {name: value for name in TRACE_CONTEXT_ATTRIBUTES if isinstance(value := extensions.get(name), str) and value}
        if "traceparent" not in carrier:
            continue
        producer = propagate.extract(carrier)
        if trace.get_current_span(producer).get_span_context().is_valid:
            return producer
    return None


class CloudEventProcessorMixin:
    """Mixin that adds CloudEvent processing capabilities.

    Provides unwrapping of nested CloudEvents, correlation-context management,
    OTel span attribute stamping, and dispatch to the EventProcessingService.

    Must be combined with a class that supplies ``registry`` and ``namespace`` attributes
    (i.e. any ``Component`` subclass).
    """

    required_cloud_event_fields: set[str] = {"specversion", "id", "source", "type"}

    async def _dispatch_cloud_event(
        self,
        cloud_event: CloudEvent[Any],
        context: dict[str, Any],
        namespace: str | None = None,
    ) -> ProcessingResult:
        """Dispatch a CloudEvent through the processing service, for one agent.

        Sets up correlation context and OTel span attributes, optionally unwraps
        Dapr-style envelopes, then delegates to EventProcessingService.
        Does **not** catch exceptions — callers are responsible for error handling.

        A delivery that arrives with no span current continues the trace its event was published
        under (``traceparent``/``tracestate``), so the processing span and everything the handler
        calls join the producer's trace instead of starting one of their own. A caller that already
        traces the delivery keeps its own span as the parent.

        Args:
            cloud_event: The CloudEvent to process
            context: Additional context for processing (mutated in place with event metadata)

        Returns:
            The processing result from the event processing service

        Raises:
            ValueError: If the processing service returns an unexpected result type
        """
        span = trace.get_current_span()
        correlation_token = None
        trace_token = None
        try:
            delivered = cloud_event
            original_event_type = cloud_event.type
            correlation_token = self.registry.correlation_context.set(getattr(cloud_event, "id", None))  # type: ignore[attr-defined]

            cloud_event, was_unwrapped = self._unwrap_nested_cloud_event(cloud_event)
            if was_unwrapped:
                self.registry.correlation_context.reset(correlation_token)  # type: ignore[attr-defined]
                correlation_token = self.registry.correlation_context.set(getattr(cloud_event, "id", None))  # type: ignore[attr-defined]

            context.update(
                {
                    "original_event_type": original_event_type,
                    "inner_event_type": cloud_event.type,
                    "was_unwrapped": was_unwrapped,
                }
            )

            span.set_attribute("event.original_type", original_event_type)
            span.set_attribute("event.inner_type", cloud_event.type)
            if was_unwrapped:
                span.set_attribute("event.unwrapped", True)

            if not span.get_span_context().is_valid:
                # Before process_event opens the delivery's first span, which then has the
                # producer's span as its parent.
                producer = producer_trace_context(cloud_event, delivered)
                if producer is not None:
                    trace_token = otel_context.attach(producer)

            processing_service = self.registry.get_service(EventProcessingService)  # type: ignore[attr-defined]
            # Which agent to dispatch to: the caller's choice where it fans one delivery out to
            # several, otherwise this endpoint's own namespace. One processing service serves the
            # process; the namespace is what tells it which chain to use.
            target = self.namespace if namespace is None else namespace  # type: ignore[attr-defined]
            processing_result = await processing_service.process_event(cloud_event, context, namespace=target)

            if not isinstance(processing_result, ProcessingResult):
                logger.error(
                    "Processing service returned unexpected result type %s",
                    type(processing_result),
                )
                raise ValueError("Invalid processing result type")

            return processing_result

        finally:
            if trace_token is not None:
                otel_context.detach(trace_token)
            if correlation_token is not None:
                self.registry.correlation_context.reset(correlation_token)  # type: ignore[attr-defined]

    def _unwrap_nested_cloud_event(
        self,
        event: CloudEvent[Any],
    ) -> tuple[CloudEvent[Any], bool]:
        """Unwrap nested CloudEvents if present.

        Handles CloudEvents wrapped in Dapr envelopes (``com.dapr.event.sent``).

        Args:
            event: The CloudEvent to potentially unwrap

        Returns:
            Tuple of (unwrapped_event, was_unwrapped)
        """
        if event.type != "com.dapr.event.sent":
            return event, False

        nested_payload: Any = event.data

        if isinstance(nested_payload, str):
            try:
                nested_payload = json.loads(nested_payload)
            except json.JSONDecodeError:
                logger.debug("Nested payload is not valid JSON, skipping unwrap")
                return event, False

        if isinstance(nested_payload, dict) and self.required_cloud_event_fields.issubset(nested_payload.keys()):
            try:
                return CloudEvent(**nested_payload), True
            except Exception as exc:
                logger.warning("Failed to parse nested CloudEvent: %s", exc, exc_info=True)
                return event, False

        logger.debug("No nested CloudEvent detected inside envelope")
        return event, False
