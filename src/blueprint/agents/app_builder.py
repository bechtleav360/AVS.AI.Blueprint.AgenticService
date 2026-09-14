"""Generic FastAPI application setup and configuration."""

import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi import FastAPI
from fastapi.routing import APIRoute

if TYPE_CHECKING:
    from .io.api.actuators.health import HealthCheckerBase

from .component.component import Component
from .component.namespace import (
    ROOT_LABEL,
    ROOT_NAMESPACE,
    construction_scope,
    current_namespace,
    namespace_of,
    qualified_entry_name,
    validate_namespace,
)
from .component.registry import DEFAULT_CACHE_NAME, Registry
from .agent.agent_builder import AgentBuilder
from .agent.agent_runtime import AgentRuntime
from .handler.event_handler_base import EventHandlerBase
from .io.api.rest_api_base import RestApiBase
from .io.api.scheduling.scheduler import SchedulerBase
from .io.api.actuators.actuator_api import ActuatorApi
from .io.api.actuators.health import CacheHealthChecker, ClientHealthChecker, HealthCheckEntry
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
from .config import DEFAULT_SETTINGS_FILES, Config, TelemetryManager
from .io.telemetry.loop_watchdog import (
    BLOCK_THRESHOLD_KEY,
    DEFAULT_BLOCK_THRESHOLD_SECONDS,
    DEFAULT_INTERVAL_SECONDS,
    WATCHDOG_ENABLED_KEY,
    WATCHDOG_INTERVAL_KEY,
    LoopWatchdog,
    configure_loop_debug,
)
from .utils import parse_bool

_UNCONSTRUCTED_KINDS = frozenset({"cache", "health_checker"})
"""Declaration kinds the replay pass does not construct.

A cache is created by ``CacheBackendFactory`` rather than by calling a class, and a health
checker is not a ``Component`` at all -- the object declared is the object used.
"""

HandlerT = TypeVar("HandlerT", bound=EventHandlerBase)
ServiceT = TypeVar("ServiceT", bound=ServiceBase)
AgentT = TypeVar("AgentT", bound=AgentRuntime)
SchedulerT = TypeVar("SchedulerT", bound=SchedulerBase)
RestApiT = TypeVar("RestApiT", bound=RestApiBase)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Declaration:
    """One ``with_*`` call recorded by an :class:`AppBuilder`, replayed by ``build()``.

    Recording rather than constructing is what lets one builder class serve both deployment
    shapes. A component built while a ``with_*`` call is running is built *before any namespace
    exists*, so it belongs to the root for ever -- which is why declaring an agent used to need
    a second class. Deferring construction to ``build()`` removes that reason.

    Attributes:
        kind: Which ``with_*`` recorded this. It names both how ``build()`` constructs it
            and, through :meth:`replay`, the method that records it again.
        target: A component class, a zero-argument factory returning one, an unbuilt
            ``AgentBuilder``, or an already-built component. ``None`` for a cache, which
            names no class.
        name: Registry name override, or ``None`` to let the component derive its own. For a
            cache this is the cache's name, which is never ``None``.
        namespace: The agent this belongs to, resolved when the call was recorded: the explicit
            ``namespace=`` argument if one was given, otherwise whatever scope was in force.
        kwargs: Constructor arguments, forwarded when ``target`` is a class or a factory. For a
            cache, the remaining ``with_cache`` arguments.
    """

    kind: str
    target: Any
    name: str | None
    namespace: str
    kwargs: Mapping[str, Any]

    @property
    def is_built(self) -> bool:
        """Whether ``target`` is a component that already exists.

        An already-built component was constructed at the caller's own source line, so it is in
        the registry before ``build()`` runs, while a class or factory is constructed during the
        replay. That difference is what ``AppBuilder._check_declaration_order`` inspects, and
        what a group refuses outright.
        """
        return isinstance(self.target, Component)

    def replay(self, builder: "AppBuilder") -> None:
        """Re-issue this call on ``builder``, which records it again.

        How a collector moves one agent's declarations onto the root builder that wires the
        process. The namespace is *not* passed: the collector opens a
        :func:`~blueprint.agents.component.namespace.namespace_scope` around the replay and
        ``_record`` reads it from there, which is the same ambient mechanism a component uses
        and the reason no namespace appears in any signature.

        The method is resolved by name with ``getattr`` rather than looked up in a table. A
        table is a second place to edit and fails with a ``KeyError`` at replay time; a missing
        attribute fails the same way but needs no maintenance, and the surfaces-agree test
        pins that every recorded ``kind`` has a method to go back to.

        Args:
            builder: The builder to record this call on.
        """
        if self.kind == "health_checker":
            # The one irregular signature: with_health_checker(name, checker) takes its name
            # positionally, where every other with_* takes it as a keyword override of a
            # derived name. Left that way because it is published API; the irregularity is
            # cheaper here, in one branch, than as a breaking change to the method.
            builder.with_health_checker(self.name or "", self.target)
            return
        arguments = () if self.target is None else (self.target,)
        getattr(builder, f"with_{self.kind}")(*arguments, name=self.name, **self.kwargs)


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

    A ``with_*()`` call **records** what to build; nothing is constructed and nothing reaches
    the registry until ``build()``. That is the property that lets one builder serve both a
    standalone application and one agent of a group: a component constructed while a ``with_*``
    call is running would be built before any namespace existed and would belong to the root
    whichever agent declared it.

    Two consequences worth knowing:

    - **A component cannot be looked up between ``with_*`` calls.** Resolve collaborators in
      ``on_startup``, which is the framework's convention anyway.
    - **An already-built instance is the exception**, because the caller constructed it at its
      own source line. It is in the registry before ``build()`` runs, so an instance recorded
      after a class registers before it -- see :meth:`_check_declaration_order`, which refuses
      the one case where that changes behaviour.

    The configuration may be given here or to ``build()``, but not both. Given here it is
    adopted immediately, which is what an existing ``AppBuilder(config)...build()`` chain does
    and what keeps its ``with_*`` logging formatted as it always was.
    """

    def __init__(self, config: Config | None = None) -> None:
        """Start a declaration.

        Args:
            config: The application's configuration. Optional so that a declaration can be
                written where no configuration is in scope -- a ``main.py`` that is only a
                declaration, or an agent of a group, whose configuration belongs to the
                process rather than to it. ``build()`` takes it instead.
        """
        self._config: Config | None = None
        if config is not None:
            self._use_config(config)
        self._telemetry_manager = TelemetryManager()
        # Every with_*() call, in call order. Order is preserved because it is meaningful:
        # handler priority ties are resolved by registration order, and build() replays this
        # list to reproduce it.
        self._declarations: list[Declaration] = []
        # build() runs once. Tracked here so that a second call says so, rather than surfacing
        # as Component.configure's "already set" from three frames down.
        self._built = False
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
        # Replaced in the lifespan when the environment wants one; the default instance is
        # never started, so shutdown can stop it unconditionally.
        self._loop_watchdog = LoopWatchdog()
        # Health checkers declared before build(), collected out of the declarations by the
        # replay pass. A dict rather than a list because the readiness payload is keyed on the
        # entry name, and a later declaration of the same name replaces an earlier one.
        self._health_checkers: list[HealthCheckEntry] = []
        # Which agents this process hosts. See the 'namespaces' property for why the
        # builder is the thing that keeps the list rather than the registry.
        self._namespaces: list[str] = []
        # Of those, the ones the deployment said it cannot run without. Read by the
        # readiness probe under readiness_policy = 'critical' (C3).
        self._critical_namespaces: list[str] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _use_config(self, config: Config) -> Config:
        """Adopt ``config`` as this application's configuration and configure logging from it.

        Logging is configured the moment a configuration arrives, whether that is in
        ``__init__`` or in ``build()``. It is the application's decision rather than the
        configuration loader's -- ``Config.__init__`` deliberately does not do it, because one
        ``Config`` per namespace would reconfigure the root logger once per agent -- and doing
        it here means an ``AppBuilder(config)`` chain still logs its own ``with_*`` calls with
        the application's format, exactly as it did when construction happened there.

        Args:
            config: The configuration to adopt.

        Returns:
            The same configuration, so callers can chain.
        """
        config.configure_logging()
        self._config = config
        return config

    def _resolve_config(self, config: Config | None) -> Config:
        """Settle which configuration ``build()`` uses, and adopt it if it is new.

        Args:
            config: What was passed to ``build()``, or ``None``.

        Returns:
            The configuration to build with: the one given here, the one given to
            ``__init__``, or -- when neither exists -- one loaded from
            :data:`~blueprint.agents.config.DEFAULT_SETTINGS_FILES`.

        Raises:
            ValueError: if a configuration was given to both ``__init__`` and ``build()``.
                Refused rather than resolved by precedence: the two are different objects with
                different trees, half the application would already have been declared against
                the first, and silently discarding one of them is the failure mode that a
                per-agent override is hardest to debug through.
        """
        if config is not None and self._config is not None:
            raise ValueError(
                "A Config was passed to both AppBuilder(config) and build(config), and there is no rule for "
                "choosing between them: they are separate trees, and whichever lost would take its log level, its "
                "app_name and every agent override with it. Pass it in exactly one place -- AppBuilder(config) for "
                "an application that has its configuration where it is declared, build(config) for one that does not."
            )
        if config is not None:
            return self._use_config(config)
        if self._config is not None:
            return self._config
        return self._use_config(Config(settings_files=DEFAULT_SETTINGS_FILES))

    @property
    def has_config(self) -> bool:
        """Whether a configuration has been supplied yet.

        A boolean rather than the object: handing out the configuration would hand out the
        *unscoped* loader, which config rework step 2b removed every path to. What a caller
        legitimately needs to know is whether this builder brought its own -- which is what
        :class:`~blueprint.agents.agent_group.AgentGroup` refuses, one process having one
        settings tree.
        """
        return self._config is not None

    @property
    def is_built(self) -> bool:
        """Whether ``build()`` has already run.

        Read by a collector, which cannot place an application that already exists: its
        components are constructed and belong to the root namespace, and ``build()`` has
        already injected the configuration process-wide.
        """
        return self._built

    def _require_config(self) -> Config:
        """Return the configuration, which exists only from ``build()`` onwards.

        Raises:
            RuntimeError: if called before ``build()`` has settled which configuration to use.
                Internal: every caller runs during or after the wiring pass.
        """
        if self._config is None:
            raise RuntimeError("The application's configuration is not settled until build() runs.")
        return self._config

    # ------------------------------------------------------------------
    # Fluent registration API
    # ------------------------------------------------------------------

    def host_agent(self, namespace: str, *, critical: bool = True) -> "AppBuilder":
        """Record that this process serves ``namespace``, whether or not it declares anything.

        Not a ``with_*``: it declares no component. It states a fact about the *process*, and
        ``build()`` needs that fact because two of the things it does are per agent rather than
        per component -- it wires one transport for each hosted agent, and it asks each agent's
        own configuration whether that agent publishes. Neither can be derived from the
        declarations, since an agent may declare no component and still have opted into
        publishing.

        Called by :class:`~blueprint.agents.agent_group.AgentGroup`, which is the object that
        was *told* the composition. The builder is not: it is handed the list, and it never
        learns that another builder exists.

        Args:
            namespace: The agent's name.
            critical: Whether the deployment can run without this agent. Carried through to the
                readiness probe, where ``readiness_policy = "critical"`` lets only the flagged
                agents take the pod out of service rotation (C3). The same flag the group
                configuration uses to decide whether a failed import stops the process
                (spec sec. 9.1), because it answers the same question -- and the default is the
                same ``True``, so an unflagged agent gates readiness exactly as it does today.

        Returns:
            This builder.

        Raises:
            ValueError: if ``namespace`` is not a legal namespace, is the root, or is already
                hosted by this process.
        """
        agent = validate_namespace(namespace)
        if not agent:
            raise ValueError("host_agent('') names no agent: '' is the root namespace, which every application already serves.")
        if agent in self._namespaces:
            raise ValueError(
                f"Namespace '{agent}' is already hosted by this process, so it cannot be declared again. Two "
                "agents cannot share a name: the name is what identifies an agent in every log line, span, queue "
                "group, durable and cache partition, so a second agent under it would be indistinguishable from "
                "the first and their components would merge into one registry namespace."
            )
        self._namespaces.append(agent)
        if critical:
            self._critical_namespaces.append(agent)
        logger.info("Hosting agent namespace '%s'%s", agent, "" if critical else " (not critical)")
        return self

    @property
    def critical_namespaces(self) -> tuple[str, ...]:
        """The hosted agents that gate readiness under the ``critical`` policy.

        A subset of :attr:`namespaces`. The root is not in it and does not need to be: it gates
        readiness under every policy, because it holds the shared infrastructure the rest of the
        process depends on.
        """
        return tuple(self._critical_namespaces)

    @property
    def namespaces(self) -> tuple[str, ...]:
        """The agent namespaces declared on this builder, in declaration order.

        The builder keeps this list because nothing else may. ``Registry`` deliberately has no
        ``get_known_namespaces()``: it is reachable from every component (C6), so an agent could
        use it to enumerate the neighbours it shares a process with -- and grouping is supposed
        to be invisible from inside. The builder is *told* the composition, by
        :meth:`host_agent`, and it is not reachable from a component, so the list lives here.

        The root namespace is not in it: a single-agent application declares no namespace at all,
        so an empty tuple means "root only" rather than "nothing registered".
        """
        return tuple(self._namespaces)

    @property
    def hosted_namespaces(self) -> tuple[str, ...]:
        """Every namespace this process serves: the root first, then each declared agent.

        The root is always present, and always first. It is where a single-agent application's
        components live, and where the framework's own root components go, so it cannot be
        conditional. In a grouped application the root usually holds nothing, and then the root
        pass over this list simply creates nothing -- the per-agent gates decide that, not this
        list.

        Distinct from :attr:`namespaces`, which is only what :meth:`host_agent` was told. That
        one answers "which agents was this builder asked to host"; this one answers "which
        namespaces does ``build()`` have to iterate", and those differ by exactly the root.
        """
        return (ROOT_NAMESPACE, *self._namespaces)

    def with_handler(
        self, handler: type[HandlerT] | HandlerT | Callable[[], HandlerT], *, name: str | None = None, **kwargs: Any
    ) -> "AppBuilder":
        """Declare an event handler class, factory or instance.

        Recorded, not built: the handler is constructed by ``build()``.

        **In a group:** prefer the class or factory form -- an already-built instance is refused
        at assembly, because its namespace and registry key were fixed where it was constructed
        (see :class:`~blueprint.agents.agent_group.AgentGroup`). This agent gets its own
        ``HandlerChain`` and its own broker subscription, so it is never offered a neighbour's
        events, and ``idempotency_enabled`` needs a cache **this** agent declared: a cache is
        private to the agent that declared it (:meth:`with_cache`).

        Args:
            handler: The handler class to build, a zero-argument callable returning one, or an
                already-built instance.
            name: Registry name override, qualified with the agent's namespace like a derived
                one.
            **kwargs: Constructor arguments, forwarded when a class or factory is passed.
        """
        if isinstance(handler, type) and not issubclass(handler, EventHandlerBase):
            raise TypeError(f"Expected EventHandlerBase subclass, got {handler.__name__}")
        return self._record("handler", handler, kwargs, name=name, method="with_handler")

    def with_service(
        self, service: type[ServiceT] | ServiceT | Callable[[], ServiceT], *, name: str | None = None, **kwargs: Any
    ) -> "AppBuilder":
        """Declare a business service. See :meth:`with_handler` for the arguments.

        **In a group:** nothing about a service changes except its registry name, which is
        qualified with the agent (``orders_order_service``), and what it resolves --
        ``self.registry`` and ``self.config`` answer for its own agent. An already-built
        instance is refused at assembly, as for every other declaration.
        """
        return self._record("service", service, kwargs, name=name, method="with_service")

    def with_agent(
        self, agent: type[AgentT] | AgentT | AgentBuilder | Callable[[], AgentT], *, name: str | None = None, **kwargs: Any
    ) -> "AppBuilder":
        """Declare an agent runtime, as a class, an unbuilt ``AgentBuilder``, a factory or an instance.

        The ``AgentBuilder`` form is the one that works in a group. ``build()`` calls
        ``agent.build(config.for_namespace(...))``, so the model, prompt and metrics are
        resolved from *this agent's* configuration view rather than from whatever was in
        scope where the chain was written::

            AppBuilder().with_agent(AgentBuilder(runtime_name="orders").with_model_from_config())

        **In a group:** the class and factory forms work too and are built inside this agent's
        scope like anything else; what they do *not* get is the scoped configuration view, so a
        runtime that reads its own model from configuration wants the ``AgentBuilder`` form. An
        already-built ``AgentRuntime`` instance is refused at assembly.

        See :meth:`with_handler` for the arguments.
        """
        return self._record("agent", agent, kwargs, name=name, method="with_agent")

    def with_scheduler(
        self, scheduler: type[SchedulerT] | SchedulerT | Callable[[], SchedulerT], *, name: str | None = None, **kwargs: Any
    ) -> "AppBuilder":
        """Declare a scheduler. See :meth:`with_handler` for the arguments.

        **In a group:** ``scheduler_mode`` is read through this agent's own configuration view,
        so one agent may run an in-process timer beside a neighbour driven by external ticks.
        Both modes need something of this agent's own -- ``"in_process"`` claims each tick in a
        cache **this** agent declared (:meth:`with_cache`), and ``"event"`` needs ``event_bus``,
        which is the group's to set. The scheduler's own REST routes move under
        ``/api/<agent>`` with every other route of this agent.
        """
        return self._record("scheduler", scheduler, kwargs, name=name, method="with_scheduler")

    def with_rest_api(
        self, api: type[RestApiT] | RestApiT | Callable[[], RestApiT], *, name: str | None = None, **kwargs: Any
    ) -> "AppBuilder":
        """Declare a custom REST API. See :meth:`with_handler` for the arguments.

        **In a group:** the routes move. A root component keeps the paths it always served
        under ``/api``; a component belonging to an agent serves them under ``/api/<agent>``,
        and its OpenAPI tags are prefixed with the agent, so two agents that declare the same
        path do not collide and each agent's operations group together in Swagger UI. Nothing in
        the component changes -- the prefix comes from ``RestApiBase.route_prefix``, which the
        namespace decides -- but a client of a grouped agent addresses the prefixed path.
        """
        return self._record("rest_api", api, kwargs, name=name, method="with_rest_api")

    @property
    def declarations(self) -> tuple[Declaration, ...]:
        """Everything recorded on this builder, in call order.

        The declaration is the builder's product until ``build()`` turns it into an
        application. Exposed because a collector assembling a group replays these itself
        instead of calling ``build()``, and because a test can assert what a ``main.py``
        declares without constructing any of it.
        """
        return tuple(self._declarations)

    def _record(self, kind: str, target: Any, kwargs: Mapping[str, Any], *, name: str | None, method: str) -> "AppBuilder":
        """Store one ``with_*`` call, settling the namespace it belongs to now rather than later.

        **There is no namespace argument, and that is the point.** A declaration takes the
        namespace in force where it is written -- the root for a standalone application, and
        the agent's own for a declaration a group is replaying inside
        :func:`namespace_scope`. So nothing a developer writes mentions a namespace, and the
        same file serves both deployment shapes unchanged.

        Settled here rather than at construction because *here* is where the caller's context
        exists; by the time the replay pass runs no scope is in force.

        One check stays at record time: an already-built instance offered while another
        agent's scope is open. It is answerable now, because the instance exists and
        ``namespace_of`` can be asked, and the offending line is where to report it.

        Args:
            kind: Which ``with_*`` this is, and therefore how ``build()`` replays it.
            target: A component class, a zero-argument factory, or a built component.
            kwargs: Constructor arguments.
            name: Registry name override, or ``None``.
            method: The builder method being called, for the error message.

        Returns:
            This builder.

        Raises:
            TypeError: if ``target`` is neither a component nor callable, or if a ``namespace``
                keyword is passed -- which was a parameter until this phase.
            ValueError: if a built instance is declared under a namespace other than its own.
        """
        if "namespace" in kwargs:
            # It was a real parameter until this phase, and dropping it would have left it
            # falling through to the component's constructor: ServiceBase and friends accept
            # one, so the call would keep working while meaning something else. Refused rather
            # than silently reinterpreted.
            raise TypeError(
                f"{method}() does not take a namespace. A declaration takes the namespace in force where it is "
                "written -- the root for a standalone application, the agent's own inside a group -- so nothing a "
                f"developer writes names one. Remove namespace={kwargs['namespace']!r}; left in place it would be "
                "forwarded to the component's constructor, which is not what it used to mean."
            )

        namespace = current_namespace()
        if isinstance(target, Component):
            built_in = namespace_of(target)
            if namespace and built_in != namespace:
                raise ValueError(
                    f"{type(target).__name__} was passed to {method}() as an instance while namespace '{namespace}' "
                    f"was in force, but it was already built in namespace '{built_in or ROOT_LABEL}', and a component "
                    "cannot change namespace afterwards: both its namespace and its registry key are fixed at "
                    f"construction. Pass the class instead -- {method}({type(target).__name__}, ...) -- so that it is "
                    "built where it is declared."
                )
        elif isinstance(target, AgentBuilder):
            if kind != "agent":
                raise TypeError(
                    f"An AgentBuilder was passed to {method}(), which declares a {kind}. An AgentBuilder produces an "
                    "AgentRuntime, so it belongs in with_agent()."
                )
        elif not callable(target):
            raise TypeError(f"{method}() needs a component class, a callable returning one, or a built component, got {target!r}.")

        self._declarations.append(Declaration(kind=kind, target=target, name=name, namespace=namespace, kwargs=dict(kwargs)))
        return self

    def _construct(self, declaration: Declaration, config: Config) -> Any:
        """Build one declaration inside its namespace -- or adopt it if it is already built.

        Registration itself does not happen here: ``Component.__init__`` adds the instance to
        the registry, so the only two things left are *which namespace it is constructed in*
        and *what it is called*.

        **The namespace is never handed to the component.** A project's component takes the
        constructor arguments its author wrote and nothing else, so the namespace travels
        through the ambient scope and is read by ``Component.__init__``. That is why
        ``with_service(OrderService, namespace="orders")`` does not become
        ``OrderService(namespace="orders")`` and does not require ``OrderService`` to know what
        a namespace is -- which is the whole point of the ambient mechanism.

        A class and a factory are treated identically, because a class *is* a zero-argument
        factory once its keyword arguments are applied. That is what lets a fluent chain be
        deferred as far as a class is.

        An unbuilt ``AgentBuilder`` is the third case, and it is the only one handed a
        configuration: ``AgentBuilder.build`` takes one, and what it must be given is the view
        scoped to *this* agent (C5), so the model, prompt and metrics of a grouped agent are
        read from its own section rather than from the root or from a neighbour's. That is the
        whole of D6, and it is why this method takes ``config`` at all.

        Args:
            declaration: The recorded call to replay.
            config: The application's configuration, scoped per declaration as needed.

        Returns:
            The component instance, already in the registry.
        """
        if declaration.is_built:
            instance = declaration.target
        elif isinstance(declaration.target, AgentBuilder):
            with construction_scope(declaration.namespace):
                instance = declaration.target.build(config.for_namespace(declaration.namespace), **declaration.kwargs)
        else:
            with construction_scope(declaration.namespace):
                instance = declaration.target(**declaration.kwargs)

        if declaration.name is not None:
            # Assigned bare: the setter qualifies it with the component's own namespace, which is
            # the single place that rule lives now. One registration applied to two agents
            # therefore registers 'orders_db' and 'billing_db' rather than colliding on 'db',
            # and either stays findable by the bare name because Registry._lookup qualifies too.
            instance.name = declaration.name
        return instance

    def with_cache(self, enabled: bool = True, enable_locking: bool = True, *, name: str = DEFAULT_CACHE_NAME) -> "AppBuilder":
        """Register a cache, by default the one every existing application already has.

        Call it more than once to register several::

            AppBuilder(config).with_cache().with_cache(name="sessions").build()

        Each name gets its own storage, isolated per backend by ``CacheBackendFactory``, and
        any component reads one back with ``self.registry.get_cache("sessions")``. There is
        deliberately no fallback from an unknown name to the default (spec sec. 8).

        **In a group:** a cache belongs to the agent that declared it and to no other (spec
        sec. 8). Two agents may both declare ``sessions`` and get separate stores -- separate
        directories on disk, separate key prefixes on Redis -- and ``get_cache("sessions")``
        resolves within the declaring agent with no fallback to a neighbour's or to the root's.
        The backend is chosen from this agent's own configuration, so one agent can run on
        Redis beside a neighbour on disk, and ``/cache/*`` is served per agent under
        ``/api/<agent>``.

        ``name`` is **keyword-only and comes last**, which is a constraint rather than a style
        choice. ``with_cache(False)`` disables caching today; had ``name`` been the first
        parameter that call would have become a cache named ``False`` with caching silently
        switched *on*, with no ``TypeError`` to notice. So ``with_cache()``,
        ``with_cache(False)`` and ``with_cache(True, False)`` all still mean what they meant.

        Recorded like every other ``with_*`` call and created by ``build()``, which is also
        what lets it be declared before any configuration exists: the backend is chosen from
        ``get_cache_config()``, and that configuration may not arrive until ``build(config)``.

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

        # Validated now, not at replay: the name becomes a directory segment and a Redis key
        # prefix, so it crosses the process boundary, and the call that wrote it is where the
        # mistake is. The factory validates again when it creates the backend -- it is the
        # rule's owner, and nothing reaches it only through here.
        CacheBackendFactory.validate_name(name)
        self._declarations.append(
            Declaration(
                kind="cache",
                target=None,
                name=name,
                namespace=current_namespace(),
                kwargs={"enable_locking": enable_locking},
            )
        )
        return self

    def _create_cache(self, declaration: Declaration, config: Config) -> None:
        """Create one declared cache and register it to the agent that declared it.

        Three things are per agent here, and each of them is what makes a cache private to the
        agent that declared it (spec sec. 8, D3):

        - **The backend is chosen from the agent's own configuration view**, so one agent in a
          group can run on redis while its neighbour uses the disk.
        - **The store is isolated by the agent as well as the name**, which
          ``CacheBackendFactory`` does from the namespace it is handed -- two agents declaring
          ``sessions`` get separate directories or separate key prefixes, not one shared store.
        - **The registry entry is keyed on the agent**, so ``get_cache("sessions")`` reaches
          this agent's and can never reach a neighbour's.

        The backend is constructed inside the agent's construction scope -- entered by the
        factory, from the namespace it is handed -- because a cache backend is itself a
        ``Component``: without it two agents' caches would both derive ``disk_cache_service``
        and collide on that one registry name.

        Args:
            declaration: A ``kind="cache"`` declaration; its ``name`` is the cache's name.
            config: The application's configuration, scoped to the declaring agent here.
        """
        name = declaration.name or DEFAULT_CACHE_NAME
        namespace = declaration.namespace
        enable_locking = bool(declaration.kwargs["enable_locking"])
        # The name and the namespace go to the factory rather than being resolved here: which
        # store they map to is backend knowledge, and the factory is where a backend is chosen
        # and where a new one would be added.
        cache_service = CacheBackendFactory.create(
            config.for_namespace(namespace).get_cache_config(),
            enable_locking=enable_locking,
            name=name,
            namespace=namespace,
        )
        registry: Registry = Component.shared_registry  # type: ignore[assignment]
        registry.add_cache(name, cache_service, namespace=namespace)
        logger.info(
            "Registered cache '%s' for agent '%s' as %s (locking=%s)",
            name,
            namespace or ROOT_LABEL,
            type(cache_service).__name__,
            enable_locking,
        )

    def with_health_checker(self, name: str, checker: "HealthCheckerBase") -> "AppBuilder":
        """Declare a custom health checker for the readiness probe.

        Recorded like every other declaration, and flushed into the ``ActuatorApi`` by
        ``build()``. Recording it is what lets a group carry an agent's checkers over with the
        rest of its declaration instead of silently dropping them.

        A checker is not a ``Component``, so it is never constructed here: the object passed
        is the object used, whichever namespace it was created in.

        **In a group:** the *agent* it belongs to is the one in force where this call is
        written, and it travels with the checker as data -- so two agents may both declare
        ``"db"`` and appear as ``orders.db`` and ``billing.db`` instead of one of them vanishing
        into the other's dict slot. Two checks that would still share one entry are refused
        rather than silently reduced to one. What a failing check then *does* is the
        deployment's decision: ``readiness_policy`` (C3) decides whether one agent's failure
        takes the whole pod out of rotation, and the default ``"all"`` says it does, which is
        what a single-agent application has always done. Whatever the policy, a failing check
        stops its agent consuming (C4) and is reported as ``blueprint.namespace.up = 0`` with
        an ERROR event (C7) -- the policy decides where traffic goes, never who is woken.

        Args:
            name: What this checker is called within its agent. It appears in the readiness
                payload under that name at the root, and under ``<agent>.<name>`` in a group.
            checker: The checker.

        Note:
            Calling this *after* ``build()`` adds the checker straight to the live
            ``ActuatorApi``, because by then the declarations have already been replayed and
            recording it would do nothing.
        """
        if self._actuator_api is not None:
            self._actuator_api.add_health_providers([HealthCheckEntry(name=name, namespace=current_namespace(), checker=checker)])
            return self
        self._declarations.append(Declaration(kind="health_checker", target=checker, name=name, namespace=current_namespace(), kwargs={}))
        return self

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _construct_declarations(self, config: Config) -> None:
        """Replay every recorded declaration, in the order it was recorded.

        This is the whole of what deferred wiring costs: one pass, in call order, each entry
        constructed inside the namespace it was recorded with. Components register themselves
        from ``Component.__init__``, so after this pass the registry holds exactly what the
        ``with_*`` calls used to put there directly.

        Caches come last, after every component. They are created through
        ``CacheBackendFactory`` rather than by a constructor, and nothing about a cache depends
        on a component or the other way round -- but a cache backend is itself a ``Component``,
        so building it in the middle of the pass would interleave it into the registry's
        insertion order and shift the components declared after it.

        Health checkers are constructed by nobody: a checker is not a ``Component``, so the
        pass only collects them for ``build()`` to hand to the actuator.

        Args:
            config: The application's configuration, handed to the declarations that take one.

        Raises:
            ValueError: if the recorded order cannot be reproduced. See
                :meth:`_check_declaration_order`.
        """
        built: list[tuple[Declaration, Any]] = []
        for entry in self._declarations:
            if entry.kind not in _UNCONSTRUCTED_KINDS:
                built.append((entry, self._construct(entry, config)))

        # After construction, not before: a class's priority is a property of the object, and
        # asking the class for it means reading a default argument and being wrong about every
        # handler that computes one. The application is not returned when this raises, so the
        # components already in the registry go nowhere.
        self._check_declaration_order(built)

        for entry in self._declarations:
            if entry.kind == "cache":
                self._create_cache(entry, config)
            elif entry.kind == "health_checker":
                self._health_checkers.append(HealthCheckEntry(name=entry.name or "", namespace=entry.namespace, checker=entry.target))

        logger.debug("Constructed %d declaration(s)", len(self._declarations))

    @staticmethod
    def _check_declaration_order(built: list[tuple[Declaration, Any]]) -> None:
        """Refuse a declaration order that construction cannot reproduce.

        An already-built instance is constructed by the caller at its own source line, so it is
        in the registry before ``build()`` runs; a class or a factory is constructed during the
        replay. So an instance recorded *after* a class registers *before* it, and registration
        order is not decoration: ``DispatchIndex.build`` resolves handler priority ties by it,
        which a project may well be relying on without having said so.

        Only handlers, only within one agent, and only at equal priority, because that is the
        only case where the order decides anything. Different priorities sort deterministically
        whichever way round the two were registered, two agents never share a chain, and
        nothing else the registry holds is order sensitive.

        Detected rather than repaired: the fix is one keyword away -- pass the class -- and
        reordering the registry behind the caller's back would make the file say one thing and
        the application do another.

        Args:
            built: Each non-cache declaration paired with the component it produced, in
                declaration order.

        Raises:
            ValueError: if a handler instance was recorded after a handler class or factory of
                the same priority in the same namespace.
        """
        handlers = [
            (position, entry, component) for position, (entry, component) in enumerate(built) if isinstance(component, EventHandlerBase)
        ]

        for position, entry, component in handlers:
            if entry.is_built:
                continue
            for later_position, later, later_component in handlers:
                if later_position <= position or not later.is_built:
                    continue
                if later.namespace != entry.namespace or later_component.priority != component.priority:
                    continue
                raise ValueError(
                    f"{type(later_component).__name__} was passed to with_handler() as an instance after "
                    f"{type(component).__name__} was declared as a class, and both have priority "
                    f"{component.priority}. An instance is built where it is written and a class is built by "
                    "build(), so the instance registers first and is tried first -- the reverse of what this file "
                    f"says. Pass {type(later_component).__name__} as a class as well, so that both are built in "
                    "declaration order, or give one of them a different priority so the order stops depending on "
                    "registration at all."
                )

    def build(self, config: Config | None = None) -> FastAPI:
        """Construct everything declared, wire it, and return the FastAPI application.

        This method:
        0. Settles the configuration and constructs every recorded declaration
        1. Injects Config into the Component class hierarchy
        2. Wires each registered scheduler for its scheduler_mode
        3. Creates the IO client, and the eventing endpoint only if something consumes
        4. Wires health checkers from all registered clients
        5. Returns a FastAPI app with lifespan management

        Args:
            config: The application's configuration, for a builder that was constructed
                without one. Omit it when ``AppBuilder(config)`` already has it.

        Returns:
            The application.

        Raises:
            ValueError: if a configuration was given twice, or if the recorded order cannot be
                reproduced (see :meth:`_check_declaration_order`).
            RuntimeError: if this builder has already been built.
        """
        if self._built:
            raise RuntimeError(
                "This AppBuilder has already been built, and a builder produces one application: build() injects "
                "the configuration into the Component hierarchy and constructs every declaration, both of which are "
                "once-per-process. Declare a new AppBuilder for a second application -- and note that the "
                "components of the first are still in the process-wide registry, so a test doing this wants "
                "Component.reset_shared_state() between cases."
            )
        self._built = True
        resolved_config = self._resolve_config(config)

        # 0. Inject config first, then construct. Nothing was built while the with_*() calls
        # ran, so this is the first moment any component exists -- and every one of them is
        # created with the configuration already in place, rather than the other way round.
        Component.configure(resolved_config)
        self._construct_declarations(resolved_config)

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
        event_bus_type = str(resolved_config.get("event_bus", "") or "").strip().lower()
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

        # 5. Create ActuatorApi and wire health checkers from all registered clients. It is
        # told the composition because the readiness probe is per agent now (C3): which
        # namespaces exist, and which of them the deployment cannot run without.
        self._actuator_api = ActuatorApi(self.hosted_namespaces, self.critical_namespaces)
        # The client's *base* name, not its registry name: the registry name is already
        # qualified with '_' ('orders_nats_client'), and the entry composes its own rendering,
        # so passing the registry name would read 'orders.orders_nats_client'. A root client's
        # base name is its registry name, so an existing payload key does not move.
        health_providers: list[HealthCheckEntry] = [
            HealthCheckEntry(name=client.base_name, namespace=client.namespace, checker=ClientHealthChecker([client]))
            for client in registry.get_clients()
        ]
        # Pull every registered cache into the readiness probe so a Redis outage takes the pod
        # out of service rotation instead of letting it silently serve cache misses. Every
        # cache, not just the default one: a named cache is a real backend with a real
        # connection, and one that only the default cache was probed would be an unreachable
        # Redis nobody was told about. The default keeps the entry name 'cache' it has always
        # had, so an existing /readiness payload is unchanged.
        for namespace, cache_name, cache in registry.cache_entries():
            name = "cache" if cache_name == DEFAULT_CACHE_NAME else f"cache:{cache_name}"
            # The agent is carried on the entry, so two agents' default caches are two entries
            # rather than one that silently reports whichever was registered last.
            health_providers.append(HealthCheckEntry(name=name, namespace=namespace, checker=CacheHealthChecker(cache)))
        health_providers.extend(self._health_checkers)
        if health_providers:
            self._actuator_api.add_health_providers(health_providers)

        # 6. Build FastAPI app
        app = FastAPI(
            title=resolved_config.get("app_name", "blueprint-service"),
            description=resolved_config.get("app_description", ""),
            version=resolved_config.get("app_version", "0.0.0"),
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
        raw = self._require_config().for_namespace(namespace).get("event_publishing_enabled", False)
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

        for namespace in self._cache_owners(registry):
            # One router per agent that has a cache, mounted under that agent's prefix, so
            # ``/api/orders/cache/stats`` reports the orders agent's cache and nothing else.
            # A process-wide endpoint would report one agent's keys to another, which is the
            # collision spec sec. 8 exists to close.
            with construction_scope(namespace):
                cache_api = CacheManagementApi()
            self._mount(app, cache_api, root_prefix="/api")

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
    def _cache_owners(registry: Registry) -> list[str]:
        """Return the namespaces that have at least one cache, in registration order.

        Derived from the registry rather than from :attr:`hosted_namespaces` because a cache is
        declared, not implied: an agent that declared none gets no endpoint at all, exactly as
        an application built without ``with_cache()`` has never served ``/cache/*``.

        Args:
            registry: The application's registry. Read process-wide, which is why this takes
                the application's own and not a component's view.
        """
        owners: list[str] = []
        for namespace, _, _ in registry.cache_entries():
            if namespace not in owners:
                owners.append(namespace)
        return owners

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
                    route.tags = [qualified_entry_name(component.namespace, str(tag)) for tag in route.tags]
        app.include_router(component.router, prefix=prefix)

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    async def _start_component(self, kind: str, component: Any, label: str) -> None:
        """Run one component's ``on_startup`` under spec sec. 9.1's failure policy.

        A failure used to end the process whoever it belonged to, and in a single-agent process
        that was right: there was one agent, and a half-started one is worse than none. In a
        group it is the blast radius grouping is paid to remove -- one agent's Redis client
        raising in ``on_startup`` would take nineteen working agents down with it.

        So the ``critical`` flag decides, and it decides *before* anything is wired rather than
        after the exception, because there is no partial build to unwind: one process, one
        ``build()``. A critical agent's failure still propagates, which aborts the lifespan
        before the port is bound, so Kubernetes crash-loops the pod with the traceback rather
        than reporting a replica that is silently short a consumer. A non-critical agent's
        failure marks that agent down and stops it consuming (C4, C7), and the rest start.

        The root is always critical: it holds the shared infrastructure, and there is no
        "rest of the process" to keep running without it.

        Args:
            kind: What sort of component this is, for the log line.
            component: The component to start.
            label: How to name it in the log line -- usually its registry name.

        Raises:
            Exception: whatever ``on_startup`` raised, when the component belongs to the root or
                to a critical agent.
        """
        try:
            await component.on_startup()
        except Exception as exc:
            namespace = namespace_of(component)
            if not namespace or namespace in self._critical_namespaces:
                logger.error("%s %s startup failed: %s", kind, label, exc, exc_info=True)
                raise
            logger.error(
                "%s %s startup failed and agent '%s' is not critical, so the process starts without it: %s",
                kind,
                label,
                namespace,
                exc,
                exc_info=True,
            )
            await self._mark_agent_down(namespace, f"its {kind.lower()} '{label}' failed to start: {exc}")
            return
        logger.info("%s %s startup completed", kind, label)

    async def _start_loop_diagnostics(self, config: Config) -> None:
        """Turn on asyncio debug mode, or start the watchdog, whichever this environment wants.

        Never both. Debug mode already reports the blocking callback with its source location,
        which is strictly better than the watchdog's "one of these agents was busy", so running
        the watchdog as well would add a second, vaguer line about the same event.

        Args:
            config: The application's configuration.
        """
        development = str(config.get("app_environment", "development")) == "development"
        if configure_loop_debug(config, development=development):
            return
        if not parse_bool(config.get(WATCHDOG_ENABLED_KEY, True), WATCHDOG_ENABLED_KEY):
            logger.info("Event loop watchdog is disabled by configuration")
            return
        self._loop_watchdog = LoopWatchdog(
            interval_seconds=float(config.get(WATCHDOG_INTERVAL_KEY, DEFAULT_INTERVAL_SECONDS)),
            threshold_seconds=float(config.get(BLOCK_THRESHOLD_KEY, DEFAULT_BLOCK_THRESHOLD_SECONDS)),
        )
        await self._loop_watchdog.start()

    async def _mark_agent_down(self, namespace: str, reason: str) -> None:
        """Take one agent out of service for a failure no health check can see.

        Latched, unlike a health-driven transition: the components of an agent whose
        ``on_startup`` raised may well answer a health check perfectly while being unusable, so
        an observed-health signal would put it straight back into service on the next poll.

        Args:
            namespace: The agent to take out of service.
            reason: Why, for the ERROR event and the readiness payload.
        """
        supervisor = self._actuator_api.supervisor if self._actuator_api is not None else None
        if supervisor is None:  # pragma: no cover - the actuator is started first
            logger.error("Agent '%s' cannot be marked down: no supervisor is running. Reason was: %s", namespace, reason)
            return
        await supervisor.mark_down(namespace, reason)

    def _create_lifespan_manager(self) -> Any:
        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            """Application lifespan manager for startup and shutdown events."""
            registry: Registry = Component.shared_registry  # type: ignore[assignment]
            resolved_config = self._require_config()
            logger.info("Starting up application components")

            # Configure OpenTelemetry tracing, one identity per agent (C2). First in startup,
            # because Component.tracer caches the provider it resolves on first use and every
            # component's first traced call happens after this point.
            try:
                self._telemetry_manager.configure_tracing(self.namespaces)
            except Exception as e:
                logger.warning("Failed to configure OpenTelemetry: %s", e)

            # A blocked event loop stalls every agent in the process at once and raises
            # nothing, so it is the one group-wide failure the process can detect about itself
            # (C7). Debug mode names the callback and is on in development; production gets the
            # watchdog instead, which names the agents that had work in flight.
            await self._start_loop_diagnostics(resolved_config)

            # ActuatorApi
            if self._actuator_api is not None:
                await self._actuator_api.on_startup()

            # Clients (IO + AI) — config reading and lazy-connect preparation
            for client in registry.get_clients():
                await self._start_component("Client", client, client.name)

            # Services (includes EventProcessingService, EventPublishingService, user services)
            for service in registry.get_services():
                await self._start_component("Service", service, service.name)

            # Handlers
            for handler in registry.get_event_handler():
                await self._start_component("Handler", handler, handler.name)

            # Agents
            for agent_name in registry.get_agents():
                await self._start_component("Agent", registry.get_component(agent_name), agent_name)

            # User REST APIs. Schedulers are excluded because SchedulerBase extends
            # RestApiBase for its trigger route, so every scheduler is in this list *and* in
            # get_schedulers() below -- driving both loops called on_startup twice on the same
            # object. Before the guard in SchedulerBase.on_startup that meant two
            # AsyncIOScheduler instances per scheduler, only one of which on_shutdown could
            # reach: every cron job fired twice in a single replica, and one timer could never
            # be stopped (#43). Their routers are still mounted from get_rest_apis() in
            # _build_rest_endpoints, which is where that inheritance is wanted.
            for rest_api in self._lifecycle_rest_apis(registry):
                await self._start_component("REST API", rest_api, rest_api.name)

            # Schedulers
            for scheduler in registry.get_schedulers():
                await self._start_component("Scheduler", scheduler, scheduler.name)

            # Eventing components (one Dapr / NATS endpoint per agent that consumes)
            for eventing_component in self._eventing_components:
                await self._start_component("Eventing component", eventing_component, eventing_component.namespace or ROOT_LABEL)

            # Routerless lifecycle components (e.g. SessionsBus).
            for lifecycle_component in self._lifecycle_components:
                await self._start_component("Lifecycle component", lifecycle_component, type(lifecycle_component).__name__)

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

            await self._loop_watchdog.stop()

            # Last, and after every on_shutdown: a component may well run its final blocking
            # work there. The pools hold non-daemon threads, so leaving them running keeps the
            # interpreter alive past the point the container was asked to stop.
            registry.shutdown_executors()

            logger.info("Application shutdown completed")

        return lifespan
