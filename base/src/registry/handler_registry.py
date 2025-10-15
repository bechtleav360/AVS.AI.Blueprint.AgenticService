"""Registry for event handlers following the memory guideline."""

import logging
from typing import Any, Dict, List, Optional

from opentelemetry import trace

from ..config import Config
from .service_registry import ServiceRegistry
from ..handler import EventHandler
from ..models import CloudEvent

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class HandlerRegistry:
    """Registry for managing event handlers in the application."""

    def __init__(self, settings: Config, service_registry: ServiceRegistry):
        self._handlers: List[EventHandler] = []
        self._settings = settings
        self._service_registry = service_registry

    def register_handler(self, handler: EventHandler) -> None:
        """Register a new event handler."""
        logger.info(
            "Registering handler: %s with priority %d", handler.name, handler.priority
        )
        handler.link_service_registry(self._service_registry)
        self._handlers.append(handler)
        # Keep handlers sorted by priority (lower numbers first)
        self._handlers.sort()

    def register_handlers(self, handlers: List[EventHandler]) -> None:
        """Register multiple event handlers."""
        for handler in handlers:
            self.register_handler(handler)

    def get_handlers(self) -> List[EventHandler]:
        """Get all registered handlers, sorted by priority."""
        return self._handlers.copy()

    async def process_event(
        self, event: CloudEvent, context: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """
        Process an event through all registered handlers.

        Returns the result from the first handler that processes the event,
        or None if no handler processes it.
        """
        if context is None:
            context = {}

        with tracer.start_as_current_span("handler_registry.process_event") as span:
            span.set_attribute("event.type", event.type)
            span.set_attribute("handlers.count", len(self._handlers))

            logger.info(
                "Processing event through %d handlers",
                len(self._handlers),
                extra={
                    "event_type": event.type,
                    "event_id": getattr(event, "id", None),
                    "handlers_count": len(self._handlers),
                },
            )

            for handler in self._handlers:
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
                    "handlers_count": len(self._handlers),
                },
            )
            return None

    def clear_handlers(self) -> None:
        """Clear all registered handlers (useful for testing)."""
        logger.info("Clearing all registered handlers")
        self._handlers.clear()
