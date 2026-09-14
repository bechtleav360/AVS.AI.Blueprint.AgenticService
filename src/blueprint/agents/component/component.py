"""Abstract base class for all framework components.

This module provides the common interface that all framework components
(EventHandler, BusinessService, AgentRuntime, RestApi, Scheduler) implement.

Concrete default implementations are provided for all lifecycle and dependency
injection methods. Subclasses only need to override what is domain-specific.
"""

from __future__ import annotations

import functools
import inspect
from abc import ABC, ABCMeta, abstractmethod
from functools import cached_property
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

from opentelemetry import trace

from ..config import Config
from ..utils import camel_to_snake
from .namespace import ROOT_NAMESPACE, qualified_component_name, validate_namespace

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

    def __init__(self, should_register: bool = True, name: str | None = None, namespace: str = ROOT_NAMESPACE) -> None:
        """Initialize the component.

        Args:
            should_register: Whether to add this instance to the shared registry.
            name: Registry name to use instead of the derived one. Passed by subclasses
                whose instances are not unique per class *and* not distinguished by a
                namespace -- ``AIClientBase`` naming itself after its provider, for example.
                An explicit name wins over the namespace-qualified one, so the caller then
                owns its uniqueness. It must be supplied here rather than assigned
                afterwards: registration happens in this constructor, so a second instance
                of the same class would collide before a rename could run.
            namespace: The agent this component belongs to; ``""`` (the default) is the root
                namespace and the whole of a single-agent application.

        Raises:
            ValueError: if the namespace is not a legal namespace. This is the framework's
                single gate for that: every component passes through this constructor,
                including the eight that opt out of registration, and it runs before the
                name is derived and before registration, so an illegal namespace cannot
                reach a registry key, a queue group, a durable name or a telemetry resource.
                Validated here rather than in ``Registry.add_component`` for those two
                reasons -- coverage of unregistered components, and ordering.
        """

        if Component.shared_registry is None:
            # Import here to avoid circular dependency
            from .registry import Registry

            Component.init_registry(Registry(Component))

        self._namespace = validate_namespace(namespace or ROOT_NAMESPACE)
        self._name = name or qualified_component_name(self._namespace, camel_to_snake(self.__class__.__name__))
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
    def namespace(self) -> str:
        """The agent this component belongs to; ``""`` for the root namespace.

        Owned by ``Component`` rather than by the bases that first needed it, so that the
        namespace cannot be assigned after the validation gate in ``__init__`` has run.
        """
        return self._namespace

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

        def _stamp_from_args(span: trace.Span, self: Component, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
            # Only worth binding/inspecting arguments if the span is actually recording —
            # a no-op span (no OTel provider configured) discards attributes anyway.
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            bound_args = bound.arguments
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

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(self: Component, *args: Any, **kwargs: Any) -> Any:
                span_name = f"{self.name}.{func.__name__}"
                with self.tracer.start_as_current_span(span_name) as span:
                    if span.is_recording():
                        _stamp_from_args(span, self, args, kwargs)
                    try:
                        return await func(self, *args, **kwargs)
                    except Exception as e:
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(self: Component, *args: Any, **kwargs: Any) -> Any:
                span_name = f"{self.name}.{func.__name__}"
                with self.tracer.start_as_current_span(span_name) as span:
                    if span.is_recording():
                        _stamp_from_args(span, self, args, kwargs)
                    try:
                        return func(self, *args, **kwargs)
                    except Exception as e:
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

            return sync_wrapper

    return decorator
