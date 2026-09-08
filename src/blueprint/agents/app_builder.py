"""Generic FastAPI application setup and configuration."""

import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, overload

from fastapi import FastAPI

if TYPE_CHECKING:
    from .io.api.actuators.health import HealthCheckerBase

from .component.component import Component
from .component.namespace import ROOT_LABEL, ROOT_NAMESPACE, namespace_of, namespace_scope, qualified_component_name, validate_namespace
from .component.registry import Registry
from .agent.agent_runtime import AgentRuntime
from .handler.event_handler_base import EventHandlerBase
from .io.api.rest_api_base import RestApiBase
from .io.api.scheduling.scheduler import SchedulerBase
from .io.api.actuators.actuator_api import ActuatorApi
from .io.api.actuators.health import CacheHealthChecker, ClientHealthChecker
from .io.api.eventing.dapr import DaprEventing
from .io.api.eventing.nats import NatsEventing
from .io.api.eventing.sessions_bus import SessionsBus
from .io.api.utilities.root import RootApi
from .io.api.utilities.cache import CacheManagementApi
from .clients.io.dapr_client import DaprClient
from .clients.io.io_client_base import TOPIC_TRANSPORTS
from .clients.io.nats_client import NATSClient
from .services.service_base import ServiceBase
from .services.eventing.event_processing_service import EventProcessingService
from .services.eventing.event_publishing_service import EventPublishingService
from .services.sessions import SessionKeyProvider, SessionsApiClient
from .services.infrastructure.cache_backend_factory import CacheBackendFactory
from .config import Config, TelemetryManager
from .utils import parse_bool

HandlerT = TypeVar("HandlerT", bound=EventHandlerBase)
ServiceT = TypeVar("ServiceT", bound=ServiceBase)
AgentT = TypeVar("AgentT", bound=AgentRuntime)
SchedulerT = TypeVar("SchedulerT", bound=SchedulerBase)
RestApiT = TypeVar("RestApiT", bound=RestApiBase)

logger = logging.getLogger(__name__)


@contextmanager
def _construction_scope(namespace: str) -> Iterator[None]:
    """Construct inside ``namespace``, or leave the ambient namespace exactly as it is.

    The difference matters because ``namespace_scope("")`` is not a no-op: it *sets* the current
    namespace to the root. :meth:`AgentRegistration.apply` opens one scope per agent and then
    calls the builder's ``with_*`` methods, which default ``namespace`` to the root -- so
    entering a scope unconditionally would reset every component of every agent back to the
    root, silently, and the ambient mechanism would apply to nothing.

    Args:
        namespace: The agent to construct for, or ``""`` to keep whatever is already in force.

    Yields:
        Nothing; the scope is ambient.
    """
    if not namespace:
        yield
        return
    with namespace_scope(namespace):
        yield


@dataclass(frozen=True)
class RegisteredComponent:
    """One component an :class:`AgentRegistration` will build when it is applied.

    Attributes:
        kind: Which ``with_*`` on the builder this entry is applied through.
        target: A component class, or a zero-argument callable returning a component.
        name: Registry name override, or ``None`` to let the component derive its own.
        kwargs: Constructor arguments, forwarded when ``target`` is a class.
    """

    kind: str
    target: Any
    name: str | None
    kwargs: Mapping[str, Any]


class AgentRegistration:
    """What an agent is made of, declared without building any of it.

    This is the shape a project's ``main.py`` takes so that the same agent can run alone or
    inside a group. It collects component *classes*; whoever applies it decides the namespace
    they are built in, which is why nothing here -- and nothing in the components themselves --
    mentions a namespace::

        registration = AgentRegistration().with_service(OrderService).with_handler(OrderHandler)

        app = AppBuilder(config).with_registration(registration).build()   # alone
        # a group applies the same object under the agent's own namespace instead

    **Nothing is instantiated until :meth:`apply` runs**, and that is the point rather than an
    optimisation: a component built here would be built before any namespace exists, and would
    belong to the root whichever agent it was declared for. So an already-constructed component
    is refused -- see :meth:`with_rest_api` for what to write instead.

    **There is no ``with_cache``.** A cache is process-wide and is registered on the
    ``AppBuilder`` that hosts the group; an agent that declared its own would either duplicate
    another agent's or quietly take it over. Ask for a cache by name from the registry instead.
    """

    def __init__(self) -> None:
        self._components: list[RegisteredComponent] = []

    @property
    def components(self) -> tuple[RegisteredComponent, ...]:
        """What has been declared, in declaration order.

        Order is preserved because it is meaningful: handler priority and scheduler wiring both
        read it, so a registration applied twice must produce the same application twice.
        """
        return tuple(self._components)

    def with_handler(self, handler: type[HandlerT], *, name: str | None = None, **kwargs: Any) -> "AgentRegistration":
        """Declare an event handler class."""
        return self._add("handler", handler, name, kwargs)

    def with_service(self, service: type[ServiceT], *, name: str | None = None, **kwargs: Any) -> "AgentRegistration":
        """Declare a business service class."""
        return self._add("service", service, name, kwargs)

    def with_agent(self, agent: type[AgentT] | Callable[[], AgentT], *, name: str | None = None, **kwargs: Any) -> "AgentRegistration":
        """Declare an agent runtime, as a class or as a factory.

        The factory form exists for the fluent builder: an ``AgentRuntime`` assembled by
        ``AgentBuilder(...).with_model_from_config()...build()`` cannot be expressed as a class
        plus keyword arguments. Wrapping that chain in a ``lambda`` defers it into
        :meth:`apply`, so the model and prompt are resolved inside the agent's own namespace
        rather than at import time::

            AgentRegistration().with_agent(lambda: AgentBuilder(config, runtime_name="orders").build())
        """
        return self._add("agent", agent, name, kwargs)

    def with_scheduler(
        self, scheduler: type[SchedulerT] | Callable[[], SchedulerT], *, name: str | None = None, **kwargs: Any
    ) -> "AgentRegistration":
        """Declare a scheduler class, or a factory returning one."""
        return self._add("scheduler", scheduler, name, kwargs)

    def with_rest_api(self, api: type[RestApiT] | Callable[[], RestApiT], *, name: str | None = None, **kwargs: Any) -> "AgentRegistration":
        """Declare a REST API class, or a factory returning one.

        Pass the class, not an instance: ``with_rest_api(OrderApi)`` rather than
        ``with_rest_api(OrderApi())``. The instance form is what an ``AppBuilder`` chain
        accepts, and it is refused here because the object would already exist -- built at
        import time, before any namespace, and therefore belonging to the root no matter which
        agent declared it. Two grouped agents each declaring one would collide on its registry
        name. Constructor arguments go here as keyword arguments; anything a plain call cannot
        express goes in a ``lambda``.
        """
        return self._add("rest_api", api, name, kwargs)

    def _add(self, kind: str, target: Any, name: str | None, kwargs: Mapping[str, Any]) -> "AgentRegistration":
        """Store one declaration, rejecting anything already built."""
        if isinstance(target, Component):
            raise TypeError(
                f"{type(target).__name__} was passed to AgentRegistration.with_{kind}() as an instance, but a "
                "registration declares components rather than holding them: this object was built before any "
                "namespace existed, so it belongs to the root namespace whichever agent declared it, and two "
                f"grouped agents declaring one would collide on its registry name. Pass the class -- "
                f"with_{kind}({type(target).__name__}, ...) with its constructor arguments as keyword arguments -- "
                "or a callable returning it."
            )
        if not callable(target):
            raise TypeError(f"AgentRegistration.with_{kind}() needs a component class or a callable returning one, got {target!r}.")
        self._components.append(RegisteredComponent(kind=kind, target=target, name=name, kwargs=dict(kwargs)))
        return self

    def apply(self, builder: "AppBuilder", namespace: str = ROOT_NAMESPACE) -> None:
        """Build everything declared here on ``builder``, inside ``namespace``.

        Public rather than private because the caller is another class: ``AppBuilder`` for a
        single agent today, the group entry point per agent later.

        Every component is constructed inside :func:`namespace_scope`, which is the whole
        mechanism -- ``Component.__init__`` reads the ambient namespace, so no component and no
        constructor signature mentions one. A factory is called here for the same reason.

        Args:
            builder: The builder to register on.
            namespace: The agent these components belong to. ``""`` is the root, which is what
                a single-agent application uses.

        Raises:
            ValueError: if ``namespace`` is not a legal namespace.
        """
        appliers: dict[str, Callable[..., Any]] = {
            "handler": builder.with_handler,
            "service": builder.with_service,
            "agent": builder.with_agent,
            "scheduler": builder.with_scheduler,
            "rest_api": builder.with_rest_api,
        }

        with namespace_scope(namespace):
            for entry in self._components:
                # A class goes to the builder, which instantiates it -- still inside this scope.
                # A factory has to be called here, because the builder would take the callable
                # itself for an already-built component.
                target = entry.target if isinstance(entry.target, type) else entry.target()
                appliers[entry.kind](target, name=entry.name, **entry.kwargs)

        logger.debug(
            "Applied %d component(s) to namespace '%s': %s",
            len(self._components),
            namespace or ROOT_LABEL,
            ", ".join(f"{entry.kind}:{getattr(entry.target, '__name__', entry.target)}" for entry in self._components),
        )


class NamespaceBuilder:
    """One agent's view of an :class:`AppBuilder`: every ``with_*`` call lands in its namespace.

    Returned by :meth:`AppBuilder.with_namespace` when no registration is passed, for the
    indent-and-close style::

        app = (
            AppBuilder(config)
            .with_namespace("orders")
                .with_service(OrderService)
                .with_handler(OrderHandler)
            .end()
            .with_namespace("billing")
                .with_service(BillingService)
            .end()
            .with_cache()
            .build()
        )

    This form is for a group assembled by hand -- a test, or agents that are not packaged as
    registrations. The primary form is
    ``with_namespace("orders", registration=orders.registration)``, which needs no ``end()``
    because it returns the ``AppBuilder`` itself.

    Every method delegates to the parent builder with ``namespace=`` filled in, so registering a
    component has one implementation and this class only decides which namespace it goes to.

    **There is no** ``with_cache``. A cache is process-wide and belongs to the ``AppBuilder``
    that hosts the group: an agent registering its own would either duplicate a neighbour's or
    quietly take it over, which is the collision spec sec. 8 exists to prevent. Ask the registry
    for a cache by name instead.
    """

    def __init__(self, builder: "AppBuilder", namespace: str) -> None:
        """Bind a namespace to a builder.

        Args:
            builder: The builder every call is forwarded to.
            namespace: The agent this view registers into.

        Raises:
            ValueError: if ``namespace`` is not a legal namespace.
        """
        self._builder = builder
        self._namespace = validate_namespace(namespace)

    @property
    def namespace(self) -> str:
        """The agent this view registers into."""
        return self._namespace

    def with_handler(self, handler: type[HandlerT] | HandlerT, *, name: str | None = None, **kwargs: Any) -> "NamespaceBuilder":
        """Register an event handler in this namespace."""
        self._builder.with_handler(handler, name=name, namespace=self._namespace, **kwargs)
        return self

    def with_service(self, service: type[ServiceT] | ServiceT, *, name: str | None = None, **kwargs: Any) -> "NamespaceBuilder":
        """Register a business service in this namespace."""
        self._builder.with_service(service, name=name, namespace=self._namespace, **kwargs)
        return self

    def with_agent(self, agent: type[AgentT] | AgentT, *, name: str | None = None, **kwargs: Any) -> "NamespaceBuilder":
        """Register an agent runtime in this namespace."""
        self._builder.with_agent(agent, name=name, namespace=self._namespace, **kwargs)
        return self

    def with_scheduler(self, scheduler: type[SchedulerT] | SchedulerT, *, name: str | None = None, **kwargs: Any) -> "NamespaceBuilder":
        """Register a scheduler in this namespace."""
        self._builder.with_scheduler(scheduler, name=name, namespace=self._namespace, **kwargs)
        return self

    def with_rest_api(self, api: type[RestApiT] | RestApiT, *, name: str | None = None, **kwargs: Any) -> "NamespaceBuilder":
        """Register a REST API in this namespace."""
        self._builder.with_rest_api(api, name=name, namespace=self._namespace, **kwargs)
        return self

    def with_registration(self, registration: AgentRegistration) -> "NamespaceBuilder":
        """Apply a whole :class:`AgentRegistration` in this namespace.

        The same thing ``with_namespace(name, registration=...)`` does, reachable from inside an
        indented block so a hand-assembled agent and a packaged one can be mixed.
        """
        self._builder.with_registration(registration, self._namespace)
        return self

    def end(self) -> "AppBuilder":
        """Close the namespace block and return the parent builder.

        Nothing is "left" in any real sense: this object holds no build state and the components
        are already registered. ``end()`` exists so the chain can continue with another
        namespace or with ``build()``.
        """
        return self._builder


class AppBuilder:
    """Builds the FastAPI application with a fluent interface.

    Usage::

        app = (
            AppBuilder(config)
            .with_handler(MyHandler)
            .with_agent(my_agent)
            .with_cache()
            .build()
        )

    Components are instantiated via with_*() calls (accepting either a class or
    an instance) and auto-register themselves in the shared registry. AppBuilder
    injects the Config in build() before the lifespan starts.
    """

    def __init__(self, config: Config) -> None:
        # Logging is configured here rather than in Config.__init__: it is the application's
        # decision, not the configuration loader's, and one Config per namespace would
        # otherwise reconfigure the root logger once per agent. This runs before any
        # with_*() call, so component construction is already logged with the right format.
        config.configure_logging()
        self._config = config
        self._telemetry_manager = TelemetryManager()
        self._eventing_component: DaprEventing | NatsEventing | None = None
        # Components that need lifespan (on_startup / on_shutdown) but do not expose
        # a FastAPI router. SessionsBus lives here because it is SSE-driven, not
        # HTTP-driven; keeping it out of _eventing_component avoids the routerless
        # special case in _build_rest_endpoints.
        self._lifecycle_components: list[Component] = []
        self._actuator_api: ActuatorApi | None = None
        # Which agents this process hosts. See the 'namespaces' property for why the
        # builder is the thing that keeps the list rather than the registry.
        self._namespaces: list[str] = []

    # ------------------------------------------------------------------
    # Fluent registration API
    # ------------------------------------------------------------------

    def with_registration(self, registration: AgentRegistration, namespace: str = ROOT_NAMESPACE) -> "AppBuilder":
        """Register everything an :class:`AgentRegistration` declares.

        This is what lets one declaration serve both deployment shapes. A project keeps its
        components in an ``AgentRegistration``, and a single-agent ``main.py`` builds it here::

            app = AppBuilder(config).with_registration(registration).with_cache().build()

        while a group applies the same object once per agent, under that agent's namespace.
        Everything above that last line is the same file in both cases.

        Equivalent to the individual ``with_*`` calls, in declaration order, so it composes with
        them and with ``with_cache``.

        Args:
            registration: The declaration to build.
            namespace: The agent these components belong to. Defaults to the root, which is the
                whole of a single-agent application.
        """
        registration.apply(self, namespace)
        return self

    @overload
    def with_namespace(self, name: str, *, registration: AgentRegistration) -> "AppBuilder": ...

    @overload
    def with_namespace(self, name: str, *, registration: None = None) -> "NamespaceBuilder": ...

    def with_namespace(self, name: str, *, registration: AgentRegistration | None = None) -> "AppBuilder | NamespaceBuilder":
        """Declare an agent hosted by this process, and register its components into it.

        Two forms, and which one you get depends on whether you hand over a registration::

            # primary: the agent is packaged, so the chain never leaves the AppBuilder
            AppBuilder(config).with_namespace("orders", registration=orders.registration)

            # hand-assembled: an indented block, closed with end()
            AppBuilder(config).with_namespace("billing").with_service(BillingService).end()

        The overloads above are what make that union tolerable at a call site: passing a
        registration is statically an ``AppBuilder`` and omitting it is statically a
        ``NamespaceBuilder``, so no caller has to narrow a union or assert its way out of one.

        **There is no** ``config`` **parameter**, and spec sec. 4.2 lists one. It would have
        nothing to do: configuration is already resolved per namespace from the one loaded tree
        -- ``Component.config`` hands each component ``Config.for_namespace(its own namespace)``,
        which tries ``<agent>.<key>`` before ``<key>`` (C5). A second ``Config`` here would
        either be ignored, or re-parse the same files once per agent and then be ignored anyway,
        because a component reads the shared one rather than anything the builder holds. Nothing
        would read it, so it is not accepted; see the changelog entry for this phase.

        Args:
            name: The agent's namespace. Must be a legal namespace and must not be the root.
            registration: The agent's declaration, applied immediately in ``name``. Omit it to
                get a :class:`NamespaceBuilder` and register components one at a time.

        Returns:
            This builder when ``registration`` was given, otherwise a :class:`NamespaceBuilder`
            for ``name``.

        Raises:
            ValueError: if ``name`` is the root namespace or is not a legal namespace.
        """
        namespace = validate_namespace(name)
        if not namespace:
            raise ValueError(
                "with_namespace('') names no agent: '' is the root namespace, which is where the plain with_*() calls "
                "already register. Pass the agent's name, or drop the with_namespace() call for a single-agent "
                "application."
            )

        # Recorded before anything is built, so that a registration failing half way through
        # still leaves the namespace declared: the startup log and the readiness policy have to
        # be able to say that an agent was meant to be here.
        if namespace not in self._namespaces:
            self._namespaces.append(namespace)
            logger.info("Hosting agent namespace '%s'", namespace)

        if registration is None:
            return NamespaceBuilder(self, namespace)
        return self.with_registration(registration, namespace)

    @property
    def namespaces(self) -> tuple[str, ...]:
        """The agent namespaces declared on this builder, in declaration order.

        The builder keeps this list because nothing else may. ``Registry`` deliberately has no
        ``get_known_namespaces()``: it is reachable from every component (C6), so an agent could
        use it to enumerate the neighbours it shares a process with -- and grouping is supposed
        to be invisible from inside. The builder is the object that was *told* which agents to
        host, and it is not reachable from a component, so the list lives here.

        The root namespace is not in it: a single-agent application declares no namespace at all,
        so an empty tuple means "root only" rather than "nothing registered".
        """
        return tuple(self._namespaces)

    def with_handler(
        self, handler: type[HandlerT] | HandlerT, *, name: str | None = None, namespace: str = ROOT_NAMESPACE, **kwargs: Any
    ) -> "AppBuilder":
        """Register an event handler class or instance.

        Args:
            handler: The handler class to build, or an already-built instance.
            name: Registry name override, qualified with the namespace like a derived one.
            namespace: The agent this handler belongs to. ``""`` keeps whatever namespace is
                already in force, which is what lets a registration applied per agent land in
                the right one.
            **kwargs: Constructor arguments, forwarded when a class is passed.
        """
        if isinstance(handler, type) and not issubclass(handler, EventHandlerBase):
            raise TypeError(f"Expected EventHandlerBase subclass, got {handler.__name__}")
        self._register(handler, namespace, kwargs, name=name, method="with_handler")
        return self

    def with_service(
        self, service: type[ServiceT] | ServiceT, *, name: str | None = None, namespace: str = ROOT_NAMESPACE, **kwargs: Any
    ) -> "AppBuilder":
        """Register a business service class or instance. See :meth:`with_handler` for the arguments."""
        self._register(service, namespace, kwargs, name=name, method="with_service")
        return self

    def with_agent(
        self, agent: type[AgentT] | AgentT, *, name: str | None = None, namespace: str = ROOT_NAMESPACE, **kwargs: Any
    ) -> "AppBuilder":
        """Register an agent runtime class or instance. See :meth:`with_handler` for the arguments."""
        self._register(agent, namespace, kwargs, name=name, method="with_agent")
        return self

    def with_scheduler(
        self, scheduler: type[SchedulerT] | SchedulerT, *, name: str | None = None, namespace: str = ROOT_NAMESPACE, **kwargs: Any
    ) -> "AppBuilder":
        """Register a scheduler class or instance. See :meth:`with_handler` for the arguments."""
        self._register(scheduler, namespace, kwargs, name=name, method="with_scheduler")
        return self

    def with_rest_api(
        self, api: type[RestApiT] | RestApiT, *, name: str | None = None, namespace: str = ROOT_NAMESPACE, **kwargs: Any
    ) -> "AppBuilder":
        """Register a custom REST API class or instance. See :meth:`with_handler` for the arguments."""
        self._register(api, namespace, kwargs, name=name, method="with_rest_api")
        return self

    @staticmethod
    def _register(target: Any, namespace: str, kwargs: Mapping[str, Any], *, name: str | None, method: str) -> Any:
        """Build ``target`` inside ``namespace`` -- or adopt it if it is already built -- and name it.

        Registration itself does not happen here: ``Component.__init__`` adds the instance to
        the registry, so the only two things left are *which namespace it is constructed in* and
        *what it is called*.

        **The namespace is never handed to** ``target``. A project's component takes the
        constructor arguments its author wrote and nothing else, so the namespace travels
        through the ambient scope and is read by ``Component.__init__``. That is why
        ``with_service(OrderService, namespace="orders")`` does not become
        ``OrderService(namespace="orders")`` and does not require ``OrderService`` to know what
        a namespace is -- which is the whole point of the ambient mechanism.

        An already-built instance cannot be moved into a namespace: its namespace, and its
        registry key with it, were fixed by the scope it was constructed in. A mismatch is
        refused rather than ignored, because ignoring it registers the component at the root
        while the caller believes it belongs to an agent.

        Args:
            target: A component class to build, or a built component to adopt.
            namespace: The agent to build inside; ``""`` keeps the ambient namespace.
            kwargs: Constructor arguments, used only when ``target`` is a class.
            name: Registry name override, or ``None`` to keep the derived name.
            method: The builder method being called, for the error message.

        Returns:
            The component instance, already in the registry.

        Raises:
            ValueError: if a built instance is offered to a namespace other than its own.
        """
        if isinstance(target, type):
            with _construction_scope(namespace):
                instance = target(**kwargs)
        else:
            built_in = namespace_of(target)
            if namespace and built_in != namespace:
                raise ValueError(
                    f"{type(target).__name__} was passed to {method}() as an instance for namespace '{namespace}', "
                    f"but it was already built in namespace '{built_in or ROOT_LABEL}', and a component cannot change "
                    "namespace afterwards: both its namespace and its registry key are fixed at construction. Pass "
                    f"the class instead -- {method}({type(target).__name__}, namespace='{namespace}', ...) -- so that "
                    "it is built inside that namespace."
                )
            instance = target

        if name is not None:
            # Qualified for the same reason Component.__init__ qualifies a derived name: one
            # registration applied to two agents would otherwise register both under the one
            # literal name, and the second would fail on the collision. It stays findable by
            # the bare name the caller wrote, because Registry._lookup tries
            # '<namespace>_<name>' before '<name>'.
            instance.name = qualified_component_name(namespace_of(instance), name)
        return instance

    def with_cache(self, enabled: bool = True, enable_locking: bool = True) -> "AppBuilder":
        """Enable persistent caching using DiskCache.

        Args:
            enabled: Whether to enable caching (default: True)
            enable_locking: Enable file-based locking for multi-deployment safety (default: True).
        """
        if enabled:
            cache_config = self._config.get_cache_config()
            cache_service = CacheBackendFactory.create(cache_config, enable_locking=enable_locking)
            Component.shared_registry.cache_service = cache_service  # type: ignore[union-attr]
            logger.info(
                "Registered %s with cache_dir=%s (locking=%s)",
                type(cache_service).__name__,
                cache_config.cache_dir,
                enable_locking,
            )
        else:
            logger.info("Caching disabled")
        return self

    def with_health_checker(self, name: str, checker: "HealthCheckerBase") -> "AppBuilder":
        """Register a custom health checker on the ActuatorApi.

        Must be called after build() has created the ActuatorApi, or the checker
        will be added during build() automatically. Prefer calling before build().
        """
        if self._actuator_api is not None:
            self._actuator_api.add_health_providers({name: checker})
        else:
            # Stored temporarily; flushed into ActuatorApi during build()
            if not hasattr(self, "_custom_health_checkers"):
                self._custom_health_checkers: dict[str, HealthCheckerBase] = {}
            self._custom_health_checkers[name] = checker
        return self

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> FastAPI:
        """Create and configure the FastAPI application.

        This method:
        1. Injects Config into the Component class hierarchy
        2. Wires each registered scheduler for its scheduler_mode
        3. Creates the IO client, and the eventing endpoint only if something consumes
        4. Wires health checkers from all registered clients
        5. Returns a FastAPI app with lifespan management
        """
        # 1. Inject config — enforced once-only by metaclass guard
        Component.configure(self._config)

        registry: Registry = Component.shared_registry  # type: ignore[assignment]

        # 2. Wire the schedulers, before step 3 decides whether this application needs a
        # transport at all. A scheduler in 'event' mode has no in-process timer:
        # its tick arrives as an event, so its tick handler must be registered by now or an
        # application whose only event consumer is a scheduler gets no transport and is never
        # ticked. wire() also adds the trigger route while the router can still be copied.
        for scheduler in registry.get_schedulers():
            tick_handler = scheduler.wire()
            if tick_handler is not None:
                logger.info(
                    "Scheduler '%s' is in event mode; its tick arrives on topic '%s' (crontab '%s')",
                    scheduler.name,
                    tick_handler.topic,
                    scheduler.crontab,
                )

        # 3. Create the IO transport client, and the eventing endpoint only if something
        # consumes. Publishing and consuming are decided separately: an application that
        # only emits events -- a scheduler that reports what it did, a REST API that hands
        # work on -- needs a client but must not be subscribed to anything it never asked
        # for. Consuming still implies publishing, because a handler returning a
        # HandlerResult with an event_type has always published through the same client.
        consumes = bool(registry.get_event_handler())
        publishes = self._publishing_requested()
        event_bus_type = str(self._config.get("event_bus", "") or "").strip().lower()

        if publishes and event_bus_type not in TOPIC_TRANSPORTS:
            # Strict where the handler branch below only warns: 'event_publishing_enabled' is
            # a new key, and setting it is an explicit statement that this application emits
            # events. Honouring that with no transport would mean the first publish fails at
            # runtime, inside whatever business operation produced the event.
            raise ValueError(
                f"'event_publishing_enabled' is true but 'event_bus' is {event_bus_type or 'not set'!r}, so there is "
                f"no client to publish through. Set 'event_bus' to one of {', '.join(TOPIC_TRANSPORTS)}, or remove "
                "'event_publishing_enabled'."
            )

        if consumes or publishes:
            if event_bus_type == "dapr":
                DaprClient()  # auto-registers
                if consumes:
                    self._eventing_component = DaprEventing()
            elif event_bus_type == "nats":
                NATSClient()  # auto-registers
                if consumes:
                    self._eventing_component = NatsEventing()
            elif event_bus_type == "sessions":
                SessionsApiClient()  # ServiceBase → auto-registers
                SessionKeyProvider()  # ServiceBase → auto-registers
                # SessionsBus has no router (SSE-driven). Track it via the
                # lifecycle list so the lifespan hook still drives on_startup /
                # on_shutdown without polluting the router-mount path.
                self._lifecycle_components.append(SessionsBus())
            else:
                logger.warning(
                    "Event handlers are registered but no valid event_bus configured "
                    "('dapr', 'nats', or 'sessions'). Event handling will be disabled."
                )

            if publishes and not consumes:
                logger.info(
                    "Event publishing is enabled without any handler: a '%s' client is created, and nothing is subscribed",
                    event_bus_type,
                )

        # 4. Create internal services (auto-register)
        # EventProcessingService is only useful when there's a handler to route
        # requests to -- whether via an eventing endpoint (see step 3) or a REST
        # API calling RestApiBase._process_resource() directly.
        if consumes:
            EventProcessingService()
        # Keyed on the client rather than on 'publishes', so a consuming application keeps
        # the publishing service it has always had without opting in.
        if registry.get_io_clients():
            EventPublishingService()

        # 5. Create ActuatorApi and wire health checkers from all registered clients
        self._actuator_api = ActuatorApi()
        health_providers: dict[str, HealthCheckerBase] = {client.name: ClientHealthChecker([client]) for client in registry.get_clients()}
        # Pull the registered cache (if any) into the readiness probe so a Redis
        # outage takes the pod out of service rotation instead of letting it
        # silently serve cache misses.
        if registry.has_cache():
            health_providers["cache"] = CacheHealthChecker(registry.cache_service)
        if hasattr(self, "_custom_health_checkers"):
            health_providers.update(self._custom_health_checkers)
        if health_providers:
            self._actuator_api.add_health_providers(health_providers)

        # 6. Build FastAPI app
        app = FastAPI(
            title=self._config.get("app_name", "blueprint-service"),
            description=self._config.get("app_description", ""),
            version=self._config.get("app_version", "0.0.0"),
            lifespan=self._create_lifespan_manager(),
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        self._build_rest_endpoints(app, registry)
        return app

    @staticmethod
    def _lifecycle_rest_apis(registry: Registry) -> list[RestApiBase]:
        """Return the REST APIs the lifespan owns, which is every one that is not a scheduler.

        A scheduler is a ``RestApiBase`` -- that is how ``POST /{name}/trigger`` reaches the
        app -- so it appears in ``get_rest_apis()`` as well as in ``get_schedulers()``. The
        lifespan drives both lists, so without this filter every scheduler's ``on_startup``
        and ``on_shutdown`` run twice.
        """
        return [rest_api for rest_api in registry.get_rest_apis() if not isinstance(rest_api, SchedulerBase)]

    def _publishing_requested(self) -> bool:
        """Report whether this application has opted into publishing events.

        ``event_publishing_enabled`` (bool, default ``False``). Off by default because
        publishing needs broker access, and a project that only wants a scheduler or a REST
        API may have none -- creating a client it never asked for would fail its readiness
        probe on a broker it does not run. Consuming applications never need the key: a
        registered handler already implies a client.

        An absent or empty value both mean "off". Empty is not treated as a typo because an
        unset environment override arrives as ``""``, and an operator writing
        ``BLUEPRINT_EVENT_PUBLISHING_ENABLED=`` means the key is not set. Anything else that
        is not a boolean does raise.

        Raises:
            ValueError: if the key holds a non-empty value that is not a boolean.
        """
        raw = self._config.get("event_publishing_enabled", False)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return False
        return parse_bool(raw, "event_publishing_enabled")

    def _build_rest_endpoints(self, app: FastAPI, registry: Registry) -> None:
        """Include all routers into the FastAPI app."""
        app.include_router(RootApi(app=app).router, tags=["root"])

        for rest_api in registry.get_rest_apis():
            # No blanket `tags=["rest"]`: it stamps every operation with a redundant "rest" tag on
            # top of its own resource tag, so the whole business API collapses into one "rest" group
            # in Swagger UI. Routes carry their per-operation tags (set via the RestApiBase decorators)
            # and group correctly; untagged routes fall under FastAPI's "default", which is the nudge
            # for services to tag their routes rather than hide behind a catch-all.
            app.include_router(rest_api.router, prefix="/api")

        if self._eventing_component is not None:
            app.include_router(self._eventing_component.router)

        if registry.has_cache():
            app.include_router(CacheManagementApi().router, prefix="/api", tags=["cache"])

        if self._actuator_api is not None:
            app.include_router(self._actuator_api.router, tags=["actuators"])

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    def _create_lifespan_manager(self) -> Any:
        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            """Application lifespan manager for startup and shutdown events."""
            registry: Registry = Component.shared_registry  # type: ignore[assignment]
            logger.info("Starting up application components")

            # Configure OpenTelemetry tracing
            try:
                self._telemetry_manager.configure_tracing()
            except Exception as e:
                logger.warning("Failed to configure OpenTelemetry: %s", e)

            # ActuatorApi
            if self._actuator_api is not None:
                await self._actuator_api.on_startup()

            # Clients (IO + AI) — config reading and lazy-connect preparation
            for client in registry.get_clients():
                try:
                    await client.on_startup()
                    logger.info("Client %s startup completed", client.name)
                except Exception as e:
                    logger.error("Client %s startup failed: %s", client.name, e, exc_info=True)
                    raise

            # Services (includes EventProcessingService, EventPublishingService, user services)
            for service in registry.get_services():
                try:
                    await service.on_startup()
                    logger.info("Service %s startup completed", service.name)
                except Exception as e:
                    logger.error("Service %s startup failed: %s", service.name, e, exc_info=True)
                    raise

            # Handlers
            for handler in registry.get_event_handler():
                try:
                    await handler.on_startup()
                    logger.info("Handler %s startup completed", handler.name)
                except Exception as e:
                    logger.error("Handler %s startup failed: %s", handler.name, e, exc_info=True)
                    raise

            # Agents
            for agent_name in registry.get_agents():
                try:
                    agent = registry.get_component(agent_name)
                    await agent.on_startup()
                    logger.info("Agent %s startup completed", agent_name)
                except Exception as e:
                    logger.error("Agent %s startup failed: %s", agent_name, e, exc_info=True)
                    raise

            # User REST APIs. Schedulers are excluded because SchedulerBase extends
            # RestApiBase for its trigger route, so every scheduler is in this list *and* in
            # get_schedulers() below -- driving both loops called on_startup twice on the same
            # object. Before the guard in SchedulerBase.on_startup that meant two
            # AsyncIOScheduler instances per scheduler, only one of which on_shutdown could
            # reach: every cron job fired twice in a single replica, and one timer could never
            # be stopped (#43). Their routers are still mounted from get_rest_apis() in
            # _build_rest_endpoints, which is where that inheritance is wanted.
            for rest_api in self._lifecycle_rest_apis(registry):
                try:
                    await rest_api.on_startup()
                    logger.info("REST API %s startup completed", rest_api.name)
                except Exception as e:
                    logger.error("REST API %s startup failed: %s", rest_api.name, e, exc_info=True)
                    raise

            # Schedulers
            for scheduler in registry.get_schedulers():
                try:
                    await scheduler.on_startup()
                    logger.info("Scheduler %s startup completed", scheduler.name)
                except Exception as e:
                    logger.error("Scheduler %s startup failed: %s", scheduler.name, e, exc_info=True)
                    raise

            # Eventing component (Dapr / NATS endpoint)
            if self._eventing_component is not None:
                try:
                    await self._eventing_component.on_startup()
                    logger.info("Eventing component startup completed")
                except Exception as e:
                    logger.error("Eventing component startup failed: %s", e, exc_info=True)
                    raise

            # Routerless lifecycle components (e.g. SessionsBus).
            for lifecycle_component in self._lifecycle_components:
                try:
                    await lifecycle_component.on_startup()
                    logger.info("Lifecycle component %s startup completed", type(lifecycle_component).__name__)
                except Exception as e:
                    logger.error(
                        "Lifecycle component %s startup failed: %s",
                        type(lifecycle_component).__name__,
                        e,
                        exc_info=True,
                    )
                    raise

            logger.info("Application startup completed")
            yield

            # ----------------------------------------------------------
            # Shutdown — reverse order
            # ----------------------------------------------------------
            logger.info("Shutting down application components")

            for lifecycle_component in reversed(self._lifecycle_components):
                try:
                    await lifecycle_component.on_shutdown()
                except Exception as e:
                    logger.error(
                        "Lifecycle component %s shutdown failed: %s",
                        type(lifecycle_component).__name__,
                        e,
                        exc_info=True,
                    )

            if self._eventing_component is not None:
                try:
                    await self._eventing_component.on_shutdown()
                except Exception as e:
                    logger.error("Eventing component shutdown failed: %s", e, exc_info=True)

            for scheduler in registry.get_schedulers():
                try:
                    await scheduler.on_shutdown()
                except Exception as e:
                    logger.error("Scheduler %s shutdown failed: %s", scheduler.name, e, exc_info=True)

            for rest_api in self._lifecycle_rest_apis(registry):
                try:
                    await rest_api.on_shutdown()
                except Exception as e:
                    logger.error("REST API %s shutdown failed: %s", rest_api.name, e, exc_info=True)

            for agent_name in registry.get_agents():
                try:
                    agent = registry.get_component(agent_name)
                    await agent.on_shutdown()
                except Exception as e:
                    logger.error("Agent %s shutdown failed: %s", agent_name, e, exc_info=True)

            for handler in registry.get_event_handler():
                try:
                    await handler.on_shutdown()
                except Exception as e:
                    logger.error("Handler %s shutdown failed: %s", handler.name, e, exc_info=True)

            for service in registry.get_services():
                try:
                    await service.on_shutdown()
                except Exception as e:
                    logger.error("Service %s shutdown failed: %s", service.name, e, exc_info=True)

            for client in registry.get_clients():
                try:
                    await client.on_shutdown()
                except Exception as e:
                    logger.error("Client %s shutdown failed: %s", client.name, e, exc_info=True)

            if self._actuator_api is not None:
                await self._actuator_api.on_shutdown()

            # Last, and after every on_shutdown: a component may well run its final blocking
            # work there. The pools hold non-daemon threads, so leaving them running keeps the
            # interpreter alive past the point the container was asked to stop.
            registry.shutdown_executors()

            logger.info("Application shutdown completed")

        return lifespan
