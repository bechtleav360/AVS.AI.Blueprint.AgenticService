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
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

from opentelemetry import trace

from ..config import Config
from ..utils import camel_to_snake
from .namespace import ROOT_NAMESPACE, current_namespace, qualified_component_name, validate_namespace

if TYPE_CHECKING:
    from .registry import Registry


class _ComponentMeta(ABCMeta):
    """Metaclass owning class-level config/registry state and their one-time initialisation.

        Both attributes are private, and the asymmetry between them is deliberate.

        ``_shared_config`` has **no** public read path. The only way for a component to reach
        configuration is the instance property ``Component.config``, which returns that component's
        own namespace view (C5) and logs any read of the raw tree. A public class-level accessor
        would defeat both: it hands out the *unscoped loader*, so an agent reads its neighbours'
        keys with no scoping and no warning. Note that ``configure()`` assigns through ``cls``, so
        the value lands on ``Component`` itself and a public name would also be reachable as
        ``self.<name>`` -- the easiest thing to type, and a silent bypass.

    ``shared_registry`` stays **public**, and not out of inconsistency: nothing is protected by
        hiding it. Looking up collaborators is the registry's whole purpose, every component already
        reaches it through the public instance property, and ``AppBuilder`` needs it before any
        component instance exists. A class-level property named ``registry`` was tried and reverted --
        it collides with the instance property of the same name, which mypy resolves in preference to
        the metaclass one.
    """

    _shared_config: Config | None = None
    shared_registry: Registry | None = None

    def configure(cls, config: Config) -> None:
        """Inject configuration once for all components. Called by AppBuilder.build().

        Raises RuntimeError if called more than once.
        """
        if cls._shared_config is not None:
            raise RuntimeError("Config is already set — can only be configured once")
        cls._shared_config = config

    def has_config(cls) -> bool:
        """Whether configuration has been injected, without handing out the loader."""
        return cls._shared_config is not None

    def reset_shared_state(cls) -> None:
        """Drop the injected config and registry. For test isolation only.

        Exists so that tests do not have to assign to the private attributes: the class-level
        state is process-wide and one-time, so a suite that builds more than one application has
        to clear it between cases.
        """
        cls._shared_config = None
        cls.shared_registry = None

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
            namespace: The agent this component belongs to. Left unset -- which is what every
                developer-written component does -- it is taken from the ambient
                ``namespace_scope`` in force during construction, so a handler or service
                carries no namespace in its own code and reads the same whether it runs alone
                or beside five other agents. ``""`` is the root namespace and the whole of a
                single-agent application.

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

        # A *non-empty* argument wins; anything else defers to the ambient scope. It cannot be
        # the other way round: ServiceBase, ClientBase, IOClientBase and EventPublishingService
        # all default this parameter to ROOT_NAMESPACE and forward it unconditionally, so a
        # developer writing `super().__init__()` in their own service passes an explicit "" --
        # and treating that as a decision would pin every developer-written component to the
        # root and make the ambient scope apply to nothing that matters.
        self._namespace = validate_namespace(namespace or current_namespace())
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
        """Get the configuration linked to this component, scoped to its namespace (C5).

        A namespaced component receives a *view*: ``get`` and the typed getters resolve
        ``<namespace>.<key>`` before the root key, so prompts, model choice and limits become
        per-agent while infrastructure keys stay shared. The view shares the loaded tree, so
        this costs one dictionary lookup, not another parse of the settings files.

        A root-namespace component gets the configuration object itself, unchanged. That is not
        an optimisation but the definition: the root namespace *is* the unscoped configuration,
        so every existing single-agent application reads exactly what it read before.
        """
        if Component._shared_config is None:
            raise RuntimeError(f"Config not linked to component '{self._name}'")
        if not self._namespace:
            return Component._shared_config
        return Component._shared_config.for_namespace(self._namespace)

    @cached_property
    def executor(self) -> ThreadPoolExecutor:
        """This component's namespace thread pool, for running blocking work off the event loop.

        Use it through ``asyncio.get_running_loop().run_in_executor(self.executor, ...)``. The
        pool belongs to the namespace, not to the component, so every component of one agent
        shares one and no agent can exhaust another's.

        Created on first access. A component that never touches this property costs nothing, so
        an application with no blocking work runs with no extra threads at all -- which is why
        this is a property rather than something ``build()`` provisions.

        Its size comes from ``executor_workers`` in this component's own configuration, which is
        namespace-scoped (C5), so one agent can be sized differently from its neighbour. The
        first component of a namespace to ask is the one that sizes it: a live pool cannot be
        resized, and the alternative -- rejecting a later disagreeing value -- would fail an
        application over a number nobody chose deliberately.
        """
        return self.registry.get_or_create_executor(self._namespace, self.config.get("executor_workers"))

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
