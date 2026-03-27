"""Handler chain for executing event handlers in priority order."""

import logging
from typing import Any

from opentelemetry import trace

from ..component.component import Component, traced
from ..models.events import CloudEvent, HandlerResult

logger = logging.getLogger(__name__)


class HandlerChain(Component):
    """Executes registered event handlers in priority order.

    Retrieves handlers from the component registry and processes events
    through them using the chain-of-responsibility pattern. Stops at the
    first handler that returns a non-None result. Re-raises any exception
    from handler execution.
    """

    def __init__(self) -> None:
        """Initialize the handler chain."""
        super().__init__(should_register=False)

    async def on_startup(self) -> None:
        """No startup actions required."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    @traced("event")
    async def process(self, event: CloudEvent, context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
        """Process event through all registered handlers in priority order.

        Args:
            event: The CloudEvent to process
            context: Processing context dictionary

        Returns:
            Result from first handler that returns non-None, or None

        Raises:
            Exception: Re-raises any exception from handler execution
        """
        handlers = sorted(self.registry.get_event_handler())
        span = trace.get_current_span()
        span.set_attribute("handlers.count", len(handlers))

        logger.debug("Processing event through %d handlers", len(handlers))

        for handler in handlers:
            try:
                if await handler.can_handle(event, context):
                    logger.info("Handler '%s' handling event '%s'", handler.name, event.type)
                    result = await handler.handle(event, context)
                    if result is not None:
                        span.set_attribute("handler.processed_by", handler.name)
                        return result
                    logger.info("Handler '%s' passed event '%s' to next handler", handler.name, event.type)

            except Exception as e:
                logger.error("Handler '%s' failed: %s", handler.name, str(e), exc_info=True)
                span.record_exception(e)
                raise

        logger.warning("No handler processed event '%s'", event.type)
        return None
