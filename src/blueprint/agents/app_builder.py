"""Generic FastAPI application setup and configuration."""

import importlib
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, overload

from fastapi import FastAPI
from fastapi.routing import APIRoute

if TYPE_CHECKING:
    from .io.api.actuators.health import HealthCheckerBase

from .component.component import Component
from .component.namespace import ROOT_LABEL, ROOT_NAMESPACE, namespace_of, namespace_scope, validate_namespace
from .component.registry import DEFAULT_CACHE_NAME, Registry
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
from .group_config import AgentSpec, GroupConfig, GroupConfigError
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
        # One transport endpoint per agent that consumes. A list rather than a single slot
        # because a group's agents each subscribe on their own behalf (spec sec. 7.6); it holds
        # exactly one element for every application that declares no namespace.
        self._eventing_components: list[DaprEventing | NatsEventing] = []
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

        if namespace in self._namespaces:
            raise ValueError(
                f"Namespace '{namespace}' is already hosted by this process, so it cannot be declared again. Two "
                "agents cannot share a name: the name is what identifies an agent in every log line, span, queue "
                "group, durable and cache partition, so a second agent under it would be indistinguishable from the "
                "first and their components would merge into one registry namespace. Give one of them a different "
                "name, or -- if this is one agent assembled from several parts -- compose the parts into a single "
                "AgentRegistration and apply that once."
            )

        # Recorded before anything is built, so that a registration failing half way through
        # still leaves the namespace declared: the startup log and the readiness policy have to
        # be able to say that an agent was meant to be here.
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

    @classmethod
    def from_group(cls, config: Config, *, environ: dict[str, str] | None = None) -> "AppBuilder":
        """Resolve this process's group and apply it, in one call.

        The convenience form of the entry point's first two lines. Kept separate from
        :meth:`with_group` because this one performs I/O -- it is ``GroupConfig.resolve`` that
        reads the environment and the group file -- while ``with_group`` does not, and a test
        that wants an exact composition needs the half that does not.

        Args:
            config: The application's configuration.
            environ: The environment to resolve from, for tests.

        Returns:
            A builder with every agent in the group applied.

        Raises:
            GroupConfigError: if the group cannot be resolved. See ``GroupConfig.resolve``.
        """
        return cls(config).with_group(GroupConfig.resolve(config, environ=environ))

    def with_group(self, group: GroupConfig) -> "AppBuilder":
        """Apply every agent in ``group``, and register the caches the group declares.

        **Performs no I/O of its own**, which is what keeps this class a pure function of its
        call sequence: no environment reads, no file reads, no ``sys.exit``, and no knowledge of
        an agent repo's layout. Those belong to ``GroupConfig.resolve`` and to the entry point,
        so a test can state an exact composition by constructing a ``GroupConfig`` literally.

        Importing an agent's module is the one thing here that reaches outside, and it is
        deliberately on this side of the line: it is driven entirely by the ``module`` strings
        the group carries, so a test points them at test modules and controls neither the
        environment nor the filesystem to do it. Imports happen **per group**, so cold start is
        proportional to the number of agents this process actually hosts rather than to the
        number the image contains.

        A critical agent that cannot be loaded raises, which the entry point turns into a
        non-zero exit before the port is bound. A non-critical one is skipped with an ERROR:
        that flag is the deployment saying it would rather run the rest (spec sec. 9.1). The
        flag is read *before* the agent is wired rather than after an exception, because there
        is no partial build to unwind -- one process, one ``build()``.

        Args:
            group: The resolved group.

        Returns:
            This builder.

        Raises:
            GroupConfigError: if a critical agent's module or registration cannot be loaded.
        """
        logger.info(
            "Applying group '%s': %d agent(s), %d declared cache(s)",
            group.name,
            len(group.agents),
            len(group.cache_names),
        )

        for spec in group.agents:
            registration = self._load_registration(spec)
            if registration is None:
                continue
            self.with_namespace(spec.name, registration=registration)

        for cache_name in group.cache_names:
            self.with_cache(name=cache_name)

        return self

    @staticmethod
    def _load_registration(spec: AgentSpec) -> AgentRegistration | None:
        """Import an agent's declaration, or report why it could not be loaded.

        Returns:
            The registration, or ``None`` when a non-critical agent could not be loaded and is
            to be skipped.

        Raises:
            GroupConfigError: if a critical agent cannot be loaded. The message names the agent
                and the module path it came from, because the two are declared in different
                files -- the agent name in the group file or an environment variable, the module
                in the image's agent map -- and which of them is wrong is the first thing to
                establish.
        """
        module_path, _, attribute = spec.module.partition(":")
        if not module_path or not attribute:
            return AppBuilder._skip_or_raise(
                spec,
                f"'{spec.module}' is not a valid declaration path. Write it as 'package.module:attribute', naming the "
                "AgentRegistration the module assigns.",
            )

        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            # Every exception, not only ImportError: importing a module runs it, so anything its
            # top level does can fail here, and an agent whose declaration raises on import is
            # exactly as unloadable as one whose module is absent.
            return AppBuilder._skip_or_raise(spec, f"importing '{module_path}' raised {type(exc).__name__}: {exc}", exc)

        registration = getattr(module, attribute, None)
        if registration is None:
            return AppBuilder._skip_or_raise(
                spec, f"module '{module_path}' has no attribute '{attribute}', so its declaration cannot be read."
            )
        if not isinstance(registration, AgentRegistration):
            return AppBuilder._skip_or_raise(
                spec,
                f"'{spec.module}' is a {type(registration).__name__}, not an AgentRegistration. An agent's "
                "declaration is the object its components are declared on.",
            )
        logger.debug("Loaded the declaration for agent '%s' from '%s'", spec.name, spec.module)
        return registration

    @staticmethod
    def _skip_or_raise(spec: AgentSpec, reason: str, cause: BaseException | None = None) -> None:
        """Raise for a critical agent, or log and skip a non-critical one.

        Raises:
            GroupConfigError: when ``spec`` is critical.
        """
        if spec.critical:
            raise GroupConfigError(f"Agent '{spec.name}' could not be loaded and is critical: {reason}") from cause
        logger.error("Agent '%s' could not be loaded and is not critical, so it is skipped: %s", spec.name, reason)
        return None

    @property
    def hosted_namespaces(self) -> tuple[str, ...]:
        """Every namespace this process serves: the root first, then each declared agent.

        The root is always present, and always first. It is where a single-agent application's
        components live, and where the framework's own root components go, so it cannot be
        conditional. In a grouped application the root usually holds nothing, and then the root
        pass over this list simply creates nothing -- the per-agent gates decide that, not this
        list.

        Distinct from :attr:`namespaces`, which is only what ``with_namespace`` was told. That
        one answers "which agents was this builder asked to host"; this one answers "which
        namespaces does ``build()`` have to iterate", and those differ by exactly the root.
        """
        return (ROOT_NAMESPACE, *self._namespaces)

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
            # Assigned bare: the setter qualifies it with the component's own namespace, which is
            # the single place that rule lives now. One registration applied to two agents
            # therefore registers 'orders_db' and 'billing_db' rather than colliding on 'db',
            # and either stays findable by the bare name because Registry._lookup qualifies too.
            instance.name = name
        return instance

    def with_cache(self, enabled: bool = True, enable_locking: bool = True, *, name: str = DEFAULT_CACHE_NAME) -> "AppBuilder":
        """Register a cache, by default the one every existing application already has.

        Call it more than once to register several::

            AppBuilder(config).with_cache().with_cache(name="sessions").build()

        Each name gets its own storage, isolated per backend by ``CacheBackendFactory``, and
        any component reads one back with ``self.registry.get_cache("sessions")``. There is
        deliberately no fallback from an unknown name to the default (spec sec. 8).

        ``name`` is **keyword-only and comes last**, which is a constraint rather than a style
        choice. ``with_cache(False)`` disables caching today; had ``name`` been the first
        parameter that call would have become a cache named ``False`` with caching silently
        switched *on*, with no ``TypeError`` to notice. So ``with_cache()``,
        ``with_cache(False)`` and ``with_cache(True, False)`` all still mean what they meant.

        Args:
            enabled: Whether to create the cache at all. ``False`` registers nothing.
            enable_locking: File-based locking for multi-process safety, for the disk backend.
            name: Which cache this is. The default keeps the registry key, the cache directory
                and the Redis keyspace an existing application already uses.

        Raises:
            ValueError: if ``name`` cannot serve as a cache name.
        """
        if not enabled:
            logger.info("Caching disabled; cache '%s' is not registered", name)
            return self

        # The name goes to the factory rather than being resolved here: which store a name
        # maps to is backend knowledge, and the factory is where a backend is chosen and where
        # a new one would be added.
        cache_service = CacheBackendFactory.create(self._config.get_cache_config(), enable_locking=enable_locking, name=name)
        # Read after the service is built, never before: a cache service is itself a Component,
        # and Component.__init__ is what creates the shared registry on first use. Capturing it
        # first is an AttributeError on None for an application whose first builder call is
        # with_cache().
        registry: Registry = Component.shared_registry  # type: ignore[assignment]
        registry.add_cache(name, cache_service)
        logger.info("Registered cache '%s' as %s (locking=%s)", name, type(cache_service).__name__, enable_locking)
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

        # 3. Create the IO transport, once per agent this process hosts. One transport type
        # per process -- 'event_bus' is read from the root config, and mixing NATS with Dapr
        # is out of scope for this plan -- but which agents get a client, and which of them
        # get an endpoint, is decided per agent below.
        event_bus_type = str(self._config.get("event_bus", "") or "").strip().lower()
        for namespace in self.hosted_namespaces:
            self._wire_transport(registry, namespace, event_bus_type)
        self._wire_dapr_endpoint(registry, event_bus_type)

        # 4. Create internal services (auto-register)
        # EventProcessingService is only useful when there's a handler to route
        # requests to -- whether via an eventing endpoint (see step 3) or a REST
        # API calling RestApiBase._process_resource() directly. One per process, at the
        # root: it keeps a handler chain per agent (phase 4) rather than being one per agent.
        if registry.get_event_handler():
            EventProcessingService()
        # One publishing service per agent that has a client, so an agent's outbound events
        # go out on its own connection (spec sec. 6) and are attributable to it. Keyed on the
        # client rather than on 'publishes', so a consuming agent keeps the publishing service
        # it has always had without opting in.
        for namespace in self.hosted_namespaces:
            if registry.get_io_clients(namespace=namespace):
                EventPublishingService(namespace=namespace)

        # 5. Create ActuatorApi and wire health checkers from all registered clients
        self._actuator_api = ActuatorApi()
        health_providers: dict[str, HealthCheckerBase] = {client.name: ClientHealthChecker([client]) for client in registry.get_clients()}
        # Pull every registered cache into the readiness probe so a Redis outage takes the pod
        # out of service rotation instead of letting it silently serve cache misses. Every
        # cache, not just the default one: a named cache is a real backend with a real
        # connection, and one that only the default cache was probed would be an unreachable
        # Redis nobody was told about. The default keeps the entry name 'cache' it has always
        # had, so an existing /readiness payload is unchanged.
        for cache_name, cache in registry.get_all_caches().items():
            entry = "cache" if cache_name == DEFAULT_CACHE_NAME else f"cache:{cache_name}"
            health_providers[entry] = CacheHealthChecker(cache)
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

    def _wire_transport(self, registry: Registry, namespace: str, event_bus_type: str) -> None:
        """Give ``namespace`` a transport client, and an endpoint if it consumes.

        Publishing and consuming are decided separately, per agent. An agent that only emits
        events -- a scheduler reporting what it did, a REST API handing work on -- needs a
        client but must not be subscribed to anything it never asked for. Consuming still
        implies publishing, because a handler returning a ``HandlerResult`` with an
        ``event_type`` has always published through the same client.

        **An agent that neither consumes nor publishes gets no client** (spec sec. 6). A
        pure-scheduler agent in ``in_process`` mode that has not opted into publishing is that
        case, and a connection for it would be a socket, a readiness dependency and a
        ``/connz`` entry for traffic that does not exist -- on a broker its own deployment may
        have no access to. This is also what makes the root pass a no-op in a grouped
        application, where every handler belongs to a namespace and the root has nothing.

        Args:
            registry: The application's registry, queried per namespace.
            namespace: The agent to wire.
            event_bus_type: The resolved ``event_bus`` value, shared by the whole process.

        Raises:
            ValueError: if this agent opted into publishing and there is no topic transport
                to publish through.
        """
        consumes = bool(registry.get_event_handler(namespace=namespace))
        publishes = self._publishing_requested(namespace)
        agent = namespace or ROOT_LABEL

        if publishes and event_bus_type not in TOPIC_TRANSPORTS:
            # Strict where the handler branch below only warns: 'event_publishing_enabled' is
            # an explicit statement that this agent emits events. Honouring that with no
            # transport would mean the first publish fails at runtime, inside whatever
            # business operation produced the event.
            raise ValueError(
                f"'event_publishing_enabled' is true for namespace '{agent}' but 'event_bus' is "
                f"{event_bus_type or 'not set'!r}, so there is no client to publish through. Set 'event_bus' to one "
                f"of {', '.join(TOPIC_TRANSPORTS)}, or remove 'event_publishing_enabled'."
            )

        if not (consumes or publishes):
            logger.debug("Namespace '%s' neither consumes nor publishes events; it is given no transport client", agent)
            return

        if event_bus_type == "dapr":
            # The client is per agent; the endpoint is not. See _wire_dapr_endpoint.
            DaprClient(namespace=namespace)  # auto-registers
        elif event_bus_type == "nats":
            NATSClient(namespace=namespace)  # auto-registers
            if consumes:
                self._eventing_components.append(NatsEventing(namespace=namespace))
        elif event_bus_type == "sessions":
            SessionsApiClient(namespace=namespace)  # ServiceBase -> auto-registers
            SessionKeyProvider(namespace=namespace)  # ServiceBase -> auto-registers
            # SessionsBus has no router (SSE-driven). Track it via the lifecycle list so the
            # lifespan hook still drives on_startup / on_shutdown without polluting the
            # router-mount path.
            self._lifecycle_components.append(SessionsBus(namespace=namespace))
        else:
            logger.warning(
                "Namespace '%s' has event handlers registered but no valid event_bus is configured "
                "('dapr', 'nats', or 'sessions'). Event handling will be disabled for it.",
                agent,
            )

        if publishes and not consumes:
            logger.info(
                "Event publishing is enabled for namespace '%s' without any handler: a '%s' client is created, and nothing is subscribed",
                agent,
                event_bus_type,
            )

    @staticmethod
    def _lifecycle_rest_apis(registry: Registry) -> list[RestApiBase]:
        """Return the REST APIs the lifespan owns, which is every one that is not a scheduler.

        A scheduler is a ``RestApiBase`` -- that is how ``POST /{name}/trigger`` reaches the
        app -- so it appears in ``get_rest_apis()`` as well as in ``get_schedulers()``. The
        lifespan drives both lists, so without this filter every scheduler's ``on_startup``
        and ``on_shutdown`` run twice.
        """
        return [rest_api for rest_api in registry.get_rest_apis() if not isinstance(rest_api, SchedulerBase)]

    def _publishing_requested(self, namespace: str = ROOT_NAMESPACE) -> bool:
        """Report whether ``namespace`` has opted into publishing events.

        ``event_publishing_enabled`` (bool, default ``False``). Off by default because
        publishing needs broker access, and a project that only wants a scheduler or a REST
        API may have none -- creating a client it never asked for would fail its readiness
        probe on a broker it does not run. Consuming applications never need the key: a
        registered handler already implies a client.

        An absent or empty value both mean "off". Empty is not treated as a typo because an
        unset environment override arrives as ``""``, and an operator writing
        ``BLUEPRINT_EVENT_PUBLISHING_ENABLED=`` means the key is not set. Anything else that
        is not a boolean does raise.

        Read through the agent's own configuration view, so one agent in a group can emit
        events while its neighbours do not (C5). ``for_namespace("")`` returns the loader
        itself, so a single-agent application reads exactly the key it always read.

        Args:
            namespace: The agent asking. ``""`` is the root.

        Raises:
            ValueError: if the key holds a non-empty value that is not a boolean.
        """
        raw = self._config.for_namespace(namespace).get("event_publishing_enabled", False)
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
            self._mount(app, rest_api, root_prefix="/api")

        for eventing_component in self._eventing_components:
            self._mount(app, eventing_component, root_prefix="")

        if registry.has_cache():
            app.include_router(CacheManagementApi().router, prefix="/api", tags=["cache"])

        if self._actuator_api is not None:
            app.include_router(self._actuator_api.router, tags=["actuators"])

    def _wire_dapr_endpoint(self, registry: Registry, event_bus_type: str) -> None:
        """Create the process's single Dapr endpoint, at the root, if anything consumes.

        One endpoint however many agents this process hosts, and that is forced rather than
        chosen. Both Dapr paths are fixed by its protocol: the sidecar fetches
        ``GET /dapr/subscribe`` from one place and posts deliveries where that document says.
        An endpoint per agent behind its own prefix would leave the sidecar with no document to
        fetch, subscribed to nothing, on a pod reporting itself healthy.

        So the endpoint is built at the root -- unprefixed, exactly where a single-agent
        application has always served it -- and it does the routing itself: the union of every
        agent's topics in the document, and one dispatch per agent that declared the delivered
        topic. NATS needs none of this, because the broker routes: one consumer per
        ``(namespace, topic)``, so its endpoints stay per agent.

        Args:
            registry: The application's registry, asked whether anything consumes at all.
            event_bus_type: The resolved ``event_bus``; anything but ``"dapr"`` returns.
        """
        if event_bus_type != "dapr" or not registry.get_event_handler():
            return
        self._eventing_components.append(DaprEventing())
        logger.info(
            "One Dapr endpoint serves this process, fanning each delivery out to the agents that declared its topic",
        )

    @staticmethod
    def _mount(app: FastAPI, component: RestApiBase, *, root_prefix: str) -> None:
        """Include one component's router, under its agent's prefix if it has one.

        ``root_prefix`` is what a *root* component keeps, and it is not the same for every
        kind: a REST API has always been mounted under ``/api``, while a transport endpoint has
        always been mounted at the top level because its paths are a contract with a sidecar.
        A namespaced component ignores it and takes ``route_prefix`` instead, so both kinds end
        up under one prefix per agent.

        The tags are rewritten rather than added to, so an agent's operations form their own
        group in Swagger UI instead of appearing twice -- once under the agent and once under
        the bare resource name. ``include_router(tags=...)`` appends, which is why this is done
        on the routes. Mutating them is safe because a router belongs to exactly one component
        and ``build()`` runs once per process (``Component.configure`` refuses a second call).

        Args:
            app: The application to mount on.
            component: The component whose router is being mounted.
            root_prefix: The prefix to use when the component belongs to the root namespace.
        """
        prefix = component.route_prefix or root_prefix
        if component.namespace:
            for route in component.router.routes:
                # A Starlette BaseRoute has no tags; an APIRoute does, and those are the
                # ones the decorators produce. Anything else is left alone.
                if isinstance(route, APIRoute) and route.tags:
                    route.tags = [f"{component.namespace}.{tag}" for tag in route.tags]
        app.include_router(component.router, prefix=prefix)

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

            # Eventing components (one Dapr / NATS endpoint per agent that consumes)
            for eventing_component in self._eventing_components:
                try:
                    await eventing_component.on_startup()
                    logger.info("Eventing component for namespace '%s' startup completed", eventing_component.namespace or ROOT_LABEL)
                except Exception as e:
                    logger.error(
                        "Eventing component for namespace '%s' startup failed: %s",
                        eventing_component.namespace or ROOT_LABEL,
                        e,
                        exc_info=True,
                    )
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

            for eventing_component in reversed(self._eventing_components):
                try:
                    await eventing_component.on_shutdown()
                except Exception as e:
                    logger.error(
                        "Eventing component for namespace '%s' shutdown failed: %s",
                        eventing_component.namespace or ROOT_LABEL,
                        e,
                        exc_info=True,
                    )

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
