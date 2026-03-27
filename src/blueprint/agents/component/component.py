"""Abstract base class for all framework components.

This module provides the common interface that all framework components
(EventHandler, BusinessService, AgentRuntime, RestApi, Scheduler) implement.

Concrete default implementations are provided for all lifecycle and dependency
injection methods. Subclasses only need to override what is domain-specific.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from abc import ABC, ABCMeta, abstractmethod
from functools import cached_property
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

from opentelemetry import trace

from ..config import Config
from ..utils import camel_to_snake

if TYPE_CHECKING:
    from .registry import Registry


class _ComponentMeta(ABCMeta):
    """Metaclass owning class-level config/registry state and their one-time initialisation."""

    shared_config: Config | None = None
    shared_registry: Registry | None = None

    @property
    def config(cls) -> Config | None:
        return cls.shared_config

    @property
    def registry(cls) -> Registry | None:
        return cls.shared_registry

    def configure(cls, config: Config) -> None:
        """Inject configuration once for all components. Called by AppBuilder.build().

        Raises RuntimeError if called more than once.
        """
        if cls.shared_config is not None:
            raise RuntimeError("Config is already set — can only be configured once")
        cls.shared_config = config

    def init_registry(cls, value: Registry) -> None:
        """Initialise the shared registry. Called lazily on the first Component.__init__().

        Raises RuntimeError if called more than once.
        """
        if cls.shared_registry is not None:
            raise RuntimeError("Registry is already set — can only be configured once")
        cls.shared_registry = value


class Component(ABC, metaclass=_ComponentMeta):
    """Abstract base class for all framework components.

    Provides concrete default implementations for the common lifecycle and
    dependency injection interface. Subclasses inherit these and only override
    what is specific to their domain:

    - Component naming and identification
    - Access to configuration and component registry
    - Lifecycle hooks for startup and shutdown

    Every Component will by default have its name set to its class name.

    Config and registry are class-level state managed by _ComponentMeta and
    injected once via Component.configure() and Component.init_registry().
    Components must NOT access self.config in __init__ — use on_startup() instead.
    """

    def __init__(self, should_register: bool = True) -> None:
        """Initialize the component."""

        if Component.shared_registry is None:
            # Import here to avoid circular dependency
            from .registry import Registry

            Component.init_registry(Registry(Component))

        self._name = camel_to_snake(self.__class__.__name__)
        if should_register:
            self.registry.add_component(self.name, self)

    @property
    def name(self) -> str:
        """Get the component name."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """Set the component name. Also updates the name in the component registry."""
        self.registry.update_component_name(self._name, value)
        self._name = value

    @property
    def registry(self) -> Registry:
        """Get the component registry for accessing other components."""
        return Component.shared_registry  # type: ignore[return-value]

    @property
    def config(self) -> Config:
        """Get the configuration linked to this component."""
        if Component.shared_config is None:
            raise RuntimeError(f"Config not linked to component '{self._name}'")
        return Component.shared_config

    @cached_property
    def tracer(self) -> trace.Tracer:
        """OTel tracer named after the concrete class."""
        return trace.get_tracer(type(self).__qualname__)

    @abstractmethod
    async def on_startup(self) -> None:
        """Called when component is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """
        raise NotImplementedError()

    @abstractmethod
    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """
        raise NotImplementedError()


def _is_cloud_event(value: Any) -> bool:
    """Duck-type check for CloudEvent — avoids circular imports."""
    return hasattr(value, "type") and hasattr(value, "source") and hasattr(value, "specversion")


def _stamp_span(span: trace.Span, name: str, value: Any) -> None:
    """Stamp a span with attributes derived from a single parameter value."""
    if _is_cloud_event(value):
        if value.type:
            span.set_attribute("event.type", value.type)
        if value.source:
            span.set_attribute("event.source", value.source)
        if getattr(value, "id", None):
            span.set_attribute("event.id", value.id)
    else:
        span.set_attribute(name, str(value))


def traced(*extract: str) -> Callable[..., Any]:
    """Decorator factory that wraps a Component method in an OTel span.

    Span name is auto-prefixed with the component's name:
        ``{self.name}.{method.__name__}``

    Each name in ``extract`` refers to a parameter of the decorated method:

    - **CloudEvent-typed value** → stamped as ``event.type``, ``event.source``,
      ``event.id`` on the span.
    - **Any other value** → stamped as ``{param_name} = str(value)``.

    With **no arguments** the first non-self parameter that looks like a
    CloudEvent is detected automatically.

    Any exception that propagates out of the method sets the span status to
    ERROR before re-raising.

    Example::

        @traced()
        async def process_event(self, event: GenericCloudEvent, ...): ...

        @traced("topic", "event")
        async def handle_event(self, topic: str, event: CloudEvent): ...

        @traced()   # no CloudEvent found — just span + error handling
        async def readiness_probe(self): ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(func)

        def _open_span_and_stamp(self: Component, bound_args: dict[str, Any]) -> trace.Span:
            span = trace.get_current_span()  # already entered via context manager below
            if extract:
                for name in extract:
                    if name in bound_args:
                        _stamp_span(span, name, bound_args[name])
            else:
                for name, value in bound_args.items():
                    if name == "self":
                        continue
                    if _is_cloud_event(value):
                        _stamp_span(span, name, value)
                        break
            return span

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(self: Component, *args: Any, **kwargs: Any) -> Any:
                bound = sig.bind(self, *args, **kwargs)
                bound.apply_defaults()
                span_name = f"{self.name}.{func.__name__}"
                with self.tracer.start_as_current_span(span_name):
                    _open_span_and_stamp(self, bound.arguments)
                    try:
                        return await func(self, *args, **kwargs)
                    except Exception as e:
                        trace.get_current_span().set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(self: Component, *args: Any, **kwargs: Any) -> Any:
                bound = sig.bind(self, *args, **kwargs)
                bound.apply_defaults()
                span_name = f"{self.name}.{func.__name__}"
                with self.tracer.start_as_current_span(span_name):
                    _open_span_and_stamp(self, bound.arguments)
                    try:
                        return func(self, *args, **kwargs)
                    except Exception as e:
                        trace.get_current_span().set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

            return sync_wrapper

    return decorator
