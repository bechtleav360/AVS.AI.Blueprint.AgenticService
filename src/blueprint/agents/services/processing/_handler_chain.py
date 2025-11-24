"""Handler chain processor for event handling."""

import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from ...models.events import CloudEvent

if TYPE_CHECKING:  # pragma: no cover
    from ...registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class _HandlerChainProcessor:
    """Processes events through registered handler chain."""

    def __init__(self, component_registry: "ComponentRegistry") -> None:
        self._component_registry: ComponentRegistry = component_registry

    async def process(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        """
        Process event through all registered handlers in priority order.

        Handlers are executed in sequence until one returns a result.

        Args:
            event: The CloudEvent to process
            context: Processing context dictionary

        Returns:
            Result from first handler that returns non-None, or None
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
                            handler._name,
                            event.type,
                            extra={
                                "handler_name": handler._name,
                                "event_type": event.type,
                                "event_id": getattr(event, "id", None),
                            },
                        )

                        result = await handler.handle(event, context)

                        if result is not None:
                            logger.info(
                                "Handler %s processed event %s and returned result",
                                handler._name,
                                event.type,
                                extra={
                                    "handler_name": handler._name,
                                    "event_type": event.type,
                                    "event_id": getattr(event, "id", None),
                                    "has_result": True,
                                },
                            )
                            span.set_attribute("handler.processed_by", handler._name)
                            return result
                        else:
                            logger.info(
                                "Handler %s processed event %s but passed to next handler",
                                handler._name,
                                event.type,
                                extra={
                                    "handler_name": handler._name,
                                    "event_type": event.type,
                                    "event_id": getattr(event, "id", None),
                                    "has_result": False,
                                },
                            )

                except Exception as e:
                    logger.error(
                        "Handler %s failed to process event %s: %s",
                        handler._name,
                        event.type,
                        str(e),
                        extra={
                            "handler_name": handler._name,
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
            logger.info(
                "No handler able to handle event %s",
                event.type,
                extra={
                    "event_type": event.type,
                    "event_id": getattr(event, "id", None),
                    "handlers_count": len(handlers),
                },
            )
            return None
