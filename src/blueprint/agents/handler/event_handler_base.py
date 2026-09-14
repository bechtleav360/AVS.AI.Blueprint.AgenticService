"""Abstract base class for event handlers in the Chain of Responsibility.

This module provides the framework-layer `EventHandler` that custom handlers
should extend.

Custom implementations MUST override the abstract methods:
- `can_handle_event()` - Determine if handler should process the event
- `handle_event()` - Process the event and return a result

Handlers can also declare published event types by overriding:
- `get_published_event_types()` - Return (success_event_type, error_event_type)
- `get_subscribed_topics()` - Return list of NATS topics to auto-subscribe on startup
- `get_handled_event_types()` - Return the event types this handler accepts, so the
  dispatch index can skip it for everything else
- `get_runtime_name()` - Return which agent runtime should serve this event

The framework provides automatic OpenTelemetry tracing for all handlers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeVar

from opentelemetry import trace

from pydantic import BaseModel, ValidationError as PydanticValidationError

from ..models import HandlerResult
from ..models.errors import InvalidEventError
from ..models.events import GenericCloudEvent
from ..component.component import Component, traced

_T = TypeVar("_T", bound=BaseModel)

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

    @property
    def priority(self) -> int:
        """Execution priority; lower numbers are tried first.

        Public because the ordering rule is enforced from outside this class:
        ``AppBuilder.build()`` compares two handlers' priorities to decide whether the order
        they were declared in still decides which of them is tried first, and ``__lt__``
        answers only the sorting question, not that one.
        """
        return self._priority

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

    def get_runtime_name(self, event: GenericCloudEvent, context: dict[str, Any]) -> str | None:
        """Declare which agent runtime should serve this event, or ``None`` to let the framework decide.

        Called between :meth:`can_handle_event` saying yes and :meth:`handle_event` running, so
        what it returns is resolved and put in ``context`` under ``"runtime"`` (the
        ``AgentRuntime``) and ``"runtime_name"`` (its registry name) **before** the handler runs.
        A handler that wants a particular runtime for a particular event therefore reads it from
        the context it is handed rather than looking it up -- and in a grouped process it gets
        its *own* agent's runtime without naming a namespace anywhere.

        Per event rather than per handler, because the choice can depend on the payload: one
        handler routing to a fast model or a thorough one on the same event type is the case
        this exists for.

        **Returning ``None`` is the normal case.** With exactly one agent runtime in this
        handler's namespace, that one is provided -- which is what a single-agent application
        has in practice. With several and no declaration, nothing is provided and the ambiguity
        is reported once: there is no basis for the framework to choose between them.

        Args:
            event: The event about to be handled.
            context: The processing context, already carrying ``request_id`` and whatever
                ``runtime_name`` the caller of ``process_event`` asked for.

        Returns:
            The registry name of the runtime to use, or ``None`` to let the framework decide.

        Example::

            def get_runtime_name(self, event, context):
                return "thorough" if event.data.get("priority") == "high" else "fast"
        """

        return None

    def get_handled_event_types(self) -> list[str]:
        """Declare the event types this handler accepts, or nothing to be offered every event.

        This is a **selection hint, not a selector**. :meth:`can_handle_event` remains the
        decision: a declared handler is still asked, and may still say no. What the declaration
        buys is that handlers which cannot possibly want an event are not asked at all, so a
        process hosting many handlers does not run every one of them against every delivery.

        **The default is an empty list, and that means "offer me everything".** It is not
        "offer me nothing", and the difference is the most destructive mistake available here:
        no handler in this framework or in any scaffolded project declares anything today, so a
        dispatch index that read an empty declaration as an empty set would silence every
        handler that exists -- and because an unhandled event is acknowledged rather than
        retried (spec sec. 7.2), the events would be consumed and discarded rather than piling
        up somewhere visible.

        **Exact event types only -- no wildcards.** A declaration is matched by equality, so
        ``"orders.*"`` would be a type no event ever has and the handler would never run.
        Declarations are checked when the index is built and a wildcard is rejected there, at
        startup, rather than being silently ignored. A handler that selects a *family* of event
        types should declare nothing and keep deciding in ``can_handle_event``.

        Returns:
            The event types this handler accepts, exactly as they appear in ``event.type``.
            Empty (the default) means every event is offered to it.

        Example::

            def get_handled_event_types(self) -> list[str]:
                return ["order.created", "order.cancelled"]
        """

        return []

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

    def extract_payload(self, event: GenericCloudEvent, payload_type: type[_T]) -> _T:
        """Extract and validate the event payload as a typed Pydantic model.

        Convenience method for handlers that expect a specific payload schema.
        Wraps validation errors in :class:`InvalidEventError`, which the framework's
        event handling infrastructure handles appropriately (e.g., Dapr returns DROP).

        Args:
            event: The CloudEvent containing the payload.
            payload_type: The Pydantic model class to validate against.

        Returns:
            A validated instance of *payload_type*.

        Raises:
            InvalidEventError: If ``event.data`` is ``None`` or fails validation.

        Example::

            async def handle_event(self, event, context):
                order = self.extract_payload(event, OrderPayload)
                # order is now a validated OrderPayload instance
        """
        if event.data is None:
            raise InvalidEventError(
                status="invalid_payload",
                reason=f"Event {event.id} has no data payload (expected {payload_type.__name__})",
            )
        try:
            return payload_type.model_validate(event.data)
        except PydanticValidationError as exc:
            raise InvalidEventError(
                status="invalid_payload",
                reason=f"Event {event.id} payload does not match {payload_type.__name__}: {exc}",
            ) from exc

    def __lt__(self, other: EventHandlerBase) -> bool:
        """Support sorting by priority."""

        return self._priority < other._priority
