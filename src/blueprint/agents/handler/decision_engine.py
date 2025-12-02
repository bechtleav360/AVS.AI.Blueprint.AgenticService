"""Chain of responsibility engine for processing events."""

import logging
from typing import Any

from opentelemetry import trace

from ..base import EventHandler
from ..models import CloudEvent

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class DecisionEngine:
    """Chain of responsibility engine for processing events."""

    def __init__(self, handlers: list[EventHandler]):
        """
        Initialize the decision engine with a list of handlers.

        Args:
            handlers: A list of event handlers to use for processing.
        """
        self.handlers = sorted(handlers)
        logger.info("Initialized with handlers: %s", [h._name for h in self.handlers])

    async def process_event(self, event: CloudEvent) -> Any | None:
        """
        Process an event through the chain of responsibility.

        Args:
            event: The CloudEvent to process.

        Returns:
            The final processing result or None if no handler produced a result.
        """
        context: dict[str, Any] = {}
        with tracer.start_as_current_span("decision_engine.process_event") as span:
            span.set_attribute("event.id", str(event.id))
            span.set_attribute("event.type", event.type)

            for handler in self.handlers:
                if await handler.can_handle(event, context):
                    span.add_event(f"Executing handler: {handler._name}")
                    try:
                        result = await handler.handle(event, context)
                        if result is not None:
                            span.set_attribute("handled_by", handler._name)
                            logger.info("Event handled by %s.", handler._name)
                            return result
                    except Exception as e:
                        logger.exception("Handler %s failed.", handler._name)
                        span.record_exception(e)
                        break  # Stop processing on error

            logger.warning("No handler produced a final result for the event.")
            return None
