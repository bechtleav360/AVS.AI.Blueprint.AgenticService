"""Abstract base class for event handlers in the Chain of Responsibility.

This module provides the framework-layer `EventHandler` that custom handlers
should extend. It follows a Template Method pattern with built-in
OpenTelemetry tracing:

- Public methods `can_handle()` and `handle()` are framework-managed wrappers
  that create spans and set common attributes.
- Custom implementations MUST override the underscored hooks
  `_can_handle()` and `_handle()` to provide domain logic only.

Benefits:
- Consistent tracing for all handlers without duplicating span code.
- Separation of concerns: framework handles cross-cutting concerns; custom
  code focuses on business logic.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from opentelemetry import trace

from ....models.events import CloudEvent

tracer = trace.get_tracer(__name__)


class EventHandler(ABC):
    """Abstract base class for event handlers in the chain of responsibility.

    Usage in custom code:

    ```python
    class MyHandler(EventHandler):
        def __init__(self):
            super().__init__("MyHandler", priority=20)

        async def _can_handle(self, event, context):
            return True

        async def _handle(self, event, context):
            # Your domain logic here (no tracing needed)
            return None
    ```
    """

    def __init__(self, name: str, priority: int = 100):
        """
        Initialize event handler.

        Args:
            name: Human-readable name for the handler.
            priority: Execution priority (lower numbers run first).
        """
        self.name = name
        self.priority = priority

    async def can_handle(self, event: CloudEvent, context: Dict[str, Any]) -> bool:
        """Wrapper that adds tracing around capability checks."""
        with tracer.start_as_current_span(f"handler.{self.name}.can_handle") as span:
            span.set_attribute("handler.name", self.name)
            span.set_attribute("handler.priority", self.priority)
            return await self._can_handle(event, context)

    async def handle(self, event: CloudEvent, context: Dict[str, Any]) -> Optional[Any]:
        """Wrapper that adds tracing around handler execution."""
        with tracer.start_as_current_span(f"handler.{self.name}.handle") as span:
            span.set_attribute("handler.name", self.name)
            span.set_attribute("handler.priority", self.priority)
            return await self._handle(event, context)

    @abstractmethod
    async def _can_handle(self, event: CloudEvent, context: Dict[str, Any]) -> bool:
        """Determine if this handler should process the event (implemented by custom)."""
        pass

    @abstractmethod
    async def _handle(self, event: CloudEvent, context: Dict[str, Any]) -> Optional[Any]:
        """Process the event and optionally return a result (implemented by custom)."""
        pass

    def __lt__(self, other: 'EventHandler') -> bool:
        """Support sorting by priority."""
        return self.priority < other.priority
