"""Abstract base class for event handlers in the Chain of Responsibility.

This module provides the framework-layer `EventHandler` that custom handlers
should extend.

Custom implementations MUST override the abstract methods:
- `can_handle_event()` - Determine if handler should process the event
- `handle_event()` - Process the event and return a result
- `get_runtime_name()` - Optionally specify which agent runtime to use

The framework provides automatic OpenTelemetry tracing for all handlers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from opentelemetry import trace

from ..models import CloudEvent
from ..registry.service_registry import ServiceRegistry

tracer = trace.get_tracer(__name__)


class EventHandler(ABC):
    """Abstract base class for event handlers in the chain of responsibility.

    Usage in custom code:

    ```python
    class MyHandler(EventHandler):
        def __init__(self):
            super().__init__("MyHandler", priority=20)

        async def can_handle_event(self, event, context):
            return True

        async def handle_event(self, event, context):
            # Your domain logic here
            return None
        
        def get_runtime_name(self, event, context):
            return "my_runtime"  # or None to skip agent
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

    def link_service_registry(self, registry: ServiceRegistry) -> None:
        """Link the service registry to the handler."""
        self._registry = registry

    async def can_handle(self, event: CloudEvent, context: Dict[str, Any]) -> bool:
        """Framework method that adds tracing around capability checks.
        
        Do not override this method. Override can_handle_event() instead.
        """
        with tracer.start_as_current_span(f"handler.{self.name}.can_handle") as span:
            span.set_attribute("handler.name", self.name)
            span.set_attribute("handler.priority", self.priority)
            return await self.can_handle_event(event, context)

    async def handle(self, event: CloudEvent, context: Dict[str, Any]) -> Optional[Any]:
        """Framework method that adds tracing around handler execution.
        
        Do not override this method. Override handle_event() instead.
        """
        with tracer.start_as_current_span(f"handler.{self.name}.handle") as span:
            span.set_attribute("handler.name", self.name)
            span.set_attribute("handler.priority", self.priority)
            return await self.handle_event(event, context)

    @abstractmethod
    async def can_handle_event(self, event: CloudEvent, context: Dict[str, Any]) -> bool:
        """Determine if this handler should process the event.
        
        Override this method in your handler implementation.
        
        Args:
            event: The CloudEvent to potentially handle.
            context: Processing context dictionary.
            
        Returns:
            True if this handler can process the event, False otherwise.
        """
        pass

    @abstractmethod
    async def handle_event(
        self, event: CloudEvent, context: Dict[str, Any]
    ) -> Optional[Any]:
        """Process the event and optionally return a result.
        
        Override this method in your handler implementation.
        
        Args:
            event: The CloudEvent to process.
            context: Processing context dictionary.
            
        Returns:
            Processing result, or None to pass to next handler.
        """
        pass

    def get_runtime_name(self, event: CloudEvent, context: Dict[str, Any]) -> Optional[str]:
        """Return the name of the agent runtime to use for this event.

        Override this method to specify which runtime should process the event.
        
        Args:
            event: The CloudEvent being processed.
            context: Processing context dictionary.

        Returns:
            Runtime name (e.g., "invoice_analyzer", "document_classifier"),
            None to skip agent processing, or empty string to use default runtime.
            
        Default implementation returns None (no agent processing).
        """
        return None

    def __lt__(self, other: "EventHandler") -> bool:
        """Support sorting by priority."""
        return self.priority < other.priority
