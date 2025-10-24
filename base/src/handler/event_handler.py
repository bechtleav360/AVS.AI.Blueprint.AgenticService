"""Abstract base class for event handlers in the Chain of Responsibility.

This module provides the framework-layer `EventHandler` that custom handlers
should extend.

Custom implementations MUST override the abstract methods:
- `can_handle_event()` - Determine if handler should process the event
- `handle_event()` - Process the event and return a result
- `get_runtime_name()` - Optionally specify which agent runtime to use

Handlers can also declare published event types by overriding:
- `get_published_event_types()` - Return (success_event_type, error_event_type)

The framework provides automatic OpenTelemetry tracing for all handlers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from opentelemetry import trace

from ..config import Config
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

    def __init__(self, name: str = "EventHandler", priority: int = 100):
        """
        Initialize event handler.

        Args:
            name: Human-readable name for the handler. Default: "EventHandler". Every handler should override this.
            priority: Execution priority (lower numbers run first).
        """

        self.name = name
        self.priority = priority
        self.config = None

        self._registry = None
        self._component_registry = None

    def add_config(self, config: Config):
        """Adds config via dependency injection, so that handlers can access environment variables during runtime
        """

        self.config = config

    def link_service_registry(self, registry: ServiceRegistry) -> None:
        """Link the service registry to the handler.
        """

        self._registry = registry

    def link_component_registry(self, registry: "ComponentRegistry") -> None:
        """Link the component registry to the handler.

        This allows handlers to access agent runtimes and other components.
        """

        self._component_registry = registry

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
    async def can_handle_event(
        self, event: CloudEvent, context: Dict[str, Any]
    ) -> bool:
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

    def _get_agent(self, agent_name: str):
        """Get a pre-configured agent from the agent registry.

        This is the recommended way to get agents using the builder pattern.
        Agents should be registered during application startup.

        Args:
            agent_name: Name of the registered agent

        Returns:
            The configured Agent instance

        Raises:
            RuntimeError: If component registry not linked
            ValueError: If agent not found

        Example:
            # Get pre-configured agent
            agent = self._get_agent("invoice_analyzer")

            # Run with instruction
            result = await agent.run(
                "Analyze this invoice...",
                deps={"invoice_text": text}
            )
        """

        if not hasattr(self, "_component_registry") or self._component_registry is None:
            raise RuntimeError(
                f"Component registry not linked to handler '{self.name}'. "
                "This is a framework initialization error."
            )

        agent_registry = self._component_registry.get_agent_registry()
        return agent_registry.get(agent_name)

    def get_published_event_types(self) -> Optional[Tuple[str, str]]:
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

    def __lt__(self, other: "EventHandler") -> bool:
        """Support sorting by priority.
        """

        return self.priority < other.priority
