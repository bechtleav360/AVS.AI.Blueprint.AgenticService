"""Abstract base class for event handlers in the Chain of Responsibility.

This module provides the framework-layer `EventHandler` that custom handlers
should extend.

Custom implementations MUST override the abstract methods:
- `can_handle_event()` - Determine if handler should process the event
- `handle_event()` - Process the event and return a result

Handlers can also declare published event types by overriding:
- `get_published_event_types()` - Return (success_event_type, error_event_type)

The framework provides automatic OpenTelemetry tracing for all handlers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from ..config import Config
from ..models import CloudEvent, HandlerResult
from .agent_runtime import AgentRuntime

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from blueprint.agents.registry.component_registry import ComponentRegistry


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

        self._name = name
        self._priority = priority
        self._config: Config | None = None

        self._component_registry: ComponentRegistry | None = None

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        return self._name

    def get_registry(self) -> ComponentRegistry:
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if not hasattr(self, "_component_registry") or self._component_registry is None:
            raise RuntimeError(f"Component registry not linked to handler '{self._name}'")
        return self._component_registry

    def get_config(self) -> Config:
        """Get the configuration linked to this handler.

        Returns:
            The Config instance linked via dependency injection

        Raises:
            RuntimeError: If config is not wired
        """

        if self._config is None:
            raise RuntimeError(f"Config not linked to handler '{self._name}'")
        return self._config

    async def on_startup(self) -> None:
        """Called when handler is registered and wired.

        Override to perform initialization tasks.
        """
        pass

    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks.
        """
        pass

    def link_config(self, config: Config) -> None:
        """Link configuration to the service via dependency injection.

        This allows services to access environment variables and configuration
        during runtime.

        Args:
            config: The Config instance
        """
        self._config = config

    def link_component_registry(self, registry: ComponentRegistry) -> None:
        """Link the component registry to the handler.

        This allows handlers to access agent runtimes and other components.
        """

        self._component_registry = registry

    async def can_handle(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Framework method that adds tracing around capability checks.

        Do not override this method. Override can_handle_event() instead.
        """

        with tracer.start_as_current_span(f"handler.{self._name}.can_handle") as span:
            span.set_attribute("handler.name", self._name)
            span.set_attribute("handler.priority", self._priority)
            return await self.can_handle_event(event, context)

    async def handle(self, event: CloudEvent, context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
        """Framework method that adds tracing around handler execution.

        Do not override this method. Override handle_event() instead.
        """

        with tracer.start_as_current_span(f"handler.{self._name}.handle") as span:
            span.set_attribute("handler.name", self._name)
            span.set_attribute("handler.priority", self._priority)
            result = await self.handle_event(event, context)

            # If result is already a HandlerResult or list of HandlerResults, return it as-is
            if isinstance(result, HandlerResult):
                return result

            if isinstance(result, list) and all(isinstance(item, HandlerResult) for item in result):
                span.set_attribute("handler.result_count", len(result))
                return result

            # If result is a dict or other type, return it as-is
            # Dicts and other types don't require event_type and data fields
            # Only HandlerResult requires those fields
            return result

    @abstractmethod
    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
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
    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
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

    def get_agent(self, agent_name: str) -> AgentRuntime:
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
            raise RuntimeError(f"Component registry not linked to handler '{self._name}'. " "This is a framework initialization error.")

        return self._component_registry.get_agent(agent_name)

    def _get_agent(self, agent_name: str):
        logger.warning("Handler '%s' is using deprecated _get_agent() method. Use get_agent() instead.", self._name)
        return self.get_agent(agent_name)

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

    def __lt__(self, other: "EventHandler") -> bool:
        """Support sorting by priority."""

        return self._priority < other._priority
