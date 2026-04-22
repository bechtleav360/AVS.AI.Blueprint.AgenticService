"""Abstract base class for event handlers in the Chain of Responsibility.

This module provides the framework-layer `EventHandler` that custom handlers
should extend.

Custom implementations MUST override the abstract methods:
- `can_handle_event()` - Determine if handler should process the event
- `handle_event()` - Process the event and return a result

Handlers can also declare published event types by overriding:
- `get_published_event_types()` - Return (success_event_type, error_event_type)
- `get_subscribed_topics()` - Return list of NATS topics to auto-subscribe on startup

The framework provides automatic OpenTelemetry tracing for all handlers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from ..models import HandlerResult
from ..models.events import GenericCloudEvent
from ..component.component import Component, traced

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EventHandlerBase(Component, ABC):
    """Abstract base class for event handlers in the chain of responsibility.

    Usage in custom code:

    ```python
    class MyHandler(EventHandler):
        def __init__(self):
            super().__init__(priority=20)
            self.name = "MyHandler"

        async def can_handle_event(self, event, context):
            return True

        async def handle_event(self, event, context):
            # Your domain logic here
            return None

        def get_runtime_name(self, event, context):
            return "my_runtime"  # or None to skip agent
    ```
    """

    def __init__(self, priority: int = 100):
        """Initialize event handler.

        Args:
            priority: Execution priority (lower numbers run first).
        """
        super().__init__()
        self._priority = priority

    @traced("event")
    async def can_handle(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        """Framework method that adds tracing around capability checks.

        Do not override this method. Override can_handle_event() instead.
        """
        trace.get_current_span().set_attribute("handler.priority", self._priority)
        return await self.can_handle_event(event, context)

    @traced("event")
    async def handle(self, event: GenericCloudEvent, context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
        """Framework method that adds tracing around handler execution.

        Do not override this method. Override handle_event() instead.
        """
        trace.get_current_span().set_attribute("handler.priority", self._priority)
        result = await self.handle_event(event, context)

        # If result is already a HandlerResult or list of HandlerResults, return it as-is
        if isinstance(result, HandlerResult):
            return result

        if isinstance(result, list) and all(isinstance(item, HandlerResult) for item in result):
            trace.get_current_span().set_attribute("handler.result_count", len(result))
            return result

        # If result is a dict or other type, return it as-is
        # Dicts and other types don't require event_type and data fields
        # Only HandlerResult requires those fields
        return result

    @abstractmethod
    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        """Determine if this handler should process the event.

        Override this method in your handler implementation.

        Args:
            event: The CloudEvent to potentially handle.
            context: Processing context dictionary.

        Returns:
            True if this handler can process the event, False otherwise.
        """

        raise NotImplementedError

    @abstractmethod
    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
        """Process the event and optionally return a result.

        Override this method in your handler implementation.

        Args:
            event: The CloudEvent to process.
            context: Processing context dictionary.

        Returns:
            Processing result. Handlers may return:

            * ``None`` to pass control to the next handler.
            * Any plain Python object for internal chaining.
            * A :class:`HandlerResult` Pydantic model that includes ``event_type``
              (str) and ``data`` (Any) fields for downstream event publication.
            * A ``list[HandlerResult]`` to publish multiple events. Each result
              with an ``event_type`` will be published as a separate event.
        """

        raise NotImplementedError

    def get_published_event_types(self) -> tuple[str, str] | None:
        """Declare the event types this handler publishes.

        Override this method to declare which event types this handler produces
        for success and error scenarios. The mapping to topics and routing keys
        is configured in the environment (values.yaml).

        Returns:
            Tuple of (success_event_type, error_event_type), or None if handler
            doesn't publish events.

        Example:
            return (
                "agent.output.invoice.processed",
                "agent.error.invoice.processing"
            )

        Default implementation returns None (no events published).
        """

        return None

    def get_subscribed_topics(self) -> list[str]:
        """Declare the NATS topics this handler subscribes to.

        Override this method to have the framework automatically subscribe to
        the listed topics on startup. Topics are deduplicated across all handlers
        and the ``nats_subscriptions`` config list before subscribing.

        Returns:
            List of NATS topic strings (supports wildcards: ``entity.>``).
            Default is an empty list — no auto-subscription.

        Example::

            def get_subscribed_topics(self) -> list[str]:
                return ["entity.created", "entity.updated", "entity.deleted"]
        """

        return []

    def __lt__(self, other: EventHandlerBase) -> bool:
        """Support sorting by priority."""

        return self._priority < other._priority
