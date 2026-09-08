"""Unified registry for managing all application components.

This registry consolidates handler, runtime, and agent management into a single
component without containing business logic. Business logic remains in
ProcessingService.

**Namespaces.** One process can host several agents, and every lookup here takes an optional
``namespace``. What it means differs between the two kinds of question, deliberately:

- *Find me the one X* (``get_component``, ``get_service``, ``get_scheduler``, ...) resolves
  **the namespace first, then the root**, because infrastructure stays shared while an agent
  overrides what it owns. This mirrors :func:`resolve_for_namespace`, which is the
  implementation.
- *Give me all the Xs* (``get_components_by_type``, ``get_services``, ...) filters to **that
  namespace exactly**, because iterating one agent's components must not sweep in a
  neighbour's.

``namespace=None``, the default, means *every namespace* and is today's behaviour unchanged. It
is not the root: ``build()`` iterating handlers has to see all of them, and a root-only default
would have silently short-changed a grouped process while looking correct on a single-agent one.

**What is deliberately absent: any way to ask which namespaces exist.** C6 forbids agent code
observing its grouping, and ``Component.registry`` is reachable from every component, so a
``get_known_namespaces()`` here would be exactly the API C6 rules out. The builder knows the
group composition because it was told; it passes each namespace to the wiring that needs one.
"""

import logging
from typing import Any, TypeVar

from ..agent.agent_runtime import AgentRuntime
from ..clients.ai.ai_client_base import AIClientBase
from ..clients.client_base import ClientBase
from ..clients.io.io_client_base import IOClientBase
from ..config.custom_logging import CorrelationContext, CorrelationContextProvider
from ..handler.event_handler_base import EventHandlerBase
from ..io.api.rest_api_base import RestApiBase
from ..io.api.scheduling.scheduler import SchedulerBase
from ..services.infrastructure.cache_service import CacheService
from ..services.service_base import ServiceBase
from ..utils import camel_to_snake
from .namespace import ROOT_LABEL, namespace_of, qualified_component_name, resolve_for_namespace

ServiceT = TypeVar("ServiceT", bound="ServiceBase")


T = TypeVar("T")

logger = logging.getLogger(__name__)


class Registry:
    """
    Unified registry for managing class instances (components) for dependency injection.

    This class is responsible ONLY for:
    - Storing and organizing components
    - Providing access to registered components
    - Managing component lifecycle (registration, retrieval)
    - Providing access to the correlation context

    Business logic belongs in service classes.
    """

    _component_class = None

    def __init__(self, component_class: Any) -> None:
        """Initialize the component registry."""

        if not isinstance(component_class, type):
            raise ValueError("component_class must be a class")

        Registry._component_class = component_class
        self._correlation_context = CorrelationContextProvider.get_correlation_context()

        self._cache_service: CacheService | None = None
        self._components: dict[str, Any] = {}

        logger.info("ComponentRegistry initialized")

    def _resolve_single(self, name_or_class: str | type[T], base_type: type[T], namespace: str | None = None) -> T:
        """Resolve a single component by name string or concrete class.

        Resolution order when a class is passed:
        1. Look up camel_to_snake(ClassName) in the registry.
        2. If not found, collect all instances of that class.
           - Exactly one → return it.
           - Zero or many → raise ValueError.

        Args:
            name_or_class: Name string or concrete class.
            base_type: The type the result must be an instance of.
            namespace: Resolve for this agent -- its own component first, then the root one.
        """
        if not isinstance(name_or_class, str):
            snake_name = camel_to_snake(name_or_class.__name__)
            if self._lookup(snake_name, namespace) is not None:
                name_or_class = snake_name  # fall through to string lookup below
            # else: pass the class to get_component for type-scan

        component = self.get_component(name_or_class, namespace)
        if not isinstance(component, base_type):
            raise ValueError(f"Component '{name_or_class}' is not a {base_type.__name__}")
        return component

    def _lookup(self, name: str, namespace: str | None) -> Any | None:
        """Return the component registered under ``name`` for ``namespace``, or ``None``.

        The namespace-qualified name is tried before the bare one, which is the whole of the
        namespace-then-root fallback: ``Component.__init__`` registers a namespaced component as
        ``<namespace>_<name>`` and a root one as ``<name>``, so asking for ``event_publishing_service``
        in namespace ``orders`` finds ``orders_event_publishing_service`` if that agent has its own
        and the shared root one otherwise.

        A caller that already holds the qualified name is unaffected: qualifying it a second time
        simply misses, and the bare lookup then finds it.
        """
        if namespace:
            qualified = qualified_component_name(namespace, name)
            if qualified in self._components:
                return self._components[qualified]
        return self._components.get(name)

    @property
    def correlation_context(self) -> CorrelationContext:
        """Return the correlation context used for logging."""

        return self._correlation_context

    @property
    def cache_service(self) -> CacheService:
        """Get the registered cache service.

        Returns:
            The cache service instance

        Raises:
            ValueError: If no cache service is registered
        """

        if self._cache_service is None:
            raise ValueError("No cache service registered")
        return self._cache_service

    @cache_service.setter
    def cache_service(self, cache_service: CacheService) -> None:
        """Register a cache service.

        Args:
            cache_service: The cache service instance to register
        """

        if self._cache_service is not None:
            raise ValueError("Cache service already registered")

        logger.info("Registering cache service: %s", type(cache_service).__name__)
        self._cache_service = cache_service

    def add_component(self, name: str, component: Any) -> None:
        """Add a component to the registry.

        Args:
            name: Name of the component to add
            component: An instance of a Component class
        """

        if not isinstance(component, self._component_class):  # type: ignore[arg-type]
            raise ValueError(f"component must be an instance of {self._component_class}")

        if name in self._components:
            raise ValueError(f"Component with name {name} already exists")

        logger.info("Adding component: %s to registry", name)
        self._components[name] = component

    def update_component_name(self, old_name: str, new_name: str) -> None:
        """Update the name of a component in the registry.

        Args:
            old_name: The old name of the component
            new_name: The new name of the component
        """

        if old_name not in self._components:
            raise ValueError(f"Component with name {old_name} does not exist")

        logger.info("Updating component name from %s to %s", old_name, new_name)
        self._components[new_name] = self._components.pop(old_name)

    def get_component(self, name_or_class: str | Any, namespace: str | None = None) -> Any:
        """Get a component from the registry.

        Args:
            name_or_class: Name of the component or class, that inherits from Component
            namespace: Resolve for this agent: its own component first, then the root one.
                ``None`` searches every namespace, which is what a single-agent application and
                every pre-namespace caller does.

        Returns:
            An instance of a Component class

        Raises:
            ValueError: if nothing matches, or if a class matches more than one component at the
                same level. Ambiguity is an error rather than a first match: silently handing an
                agent a neighbour's collaborator is the attribution the namespace exists to give.
        """

        if not isinstance(name_or_class, str):
            candidates = self.get_components_by_type(name_or_class)
            if namespace is not None:
                return resolve_for_namespace(candidates, namespace, description=f"component of type {name_or_class}")
            if len(candidates) == 0:
                raise ValueError(f"No components of type {name_or_class} found")
            if len(candidates) > 1:
                names = self.get_component_names_by_type(name_or_class)
                raise ValueError(f"Multiple components of type {name_or_class} found: {names}")
            return candidates[0]

        component = self._lookup(name_or_class, namespace)
        if component is None:
            in_namespace = "" if namespace is None else f" in namespace '{namespace or ROOT_LABEL}' or at the root"
            raise ValueError(f"Component with name {name_or_class} does not exist{in_namespace}")
        return component

    def get_components_by_type(self, component_type: Any, namespace: str | None = None) -> list[Any]:
        """Get all components from the registry of a specific type.

        Args:
            component_type: The type of the components to retrieve
            namespace: Return only this agent's components. Filtered on the component's own
                ``namespace`` rather than on its registry name, so a component registered under
                an explicit name is still attributed correctly. ``None`` returns every
                namespace, which is what iteration over the whole application wants.

        Returns:
            A list of components
        """

        return [
            component
            for component in self._components.values()
            if isinstance(component, component_type) and (namespace is None or namespace_of(component) == namespace)
        ]

    def get_component_names_by_type(self, component_type: Any, namespace: str | None = None) -> list[str]:
        """Get all component names from the registry of a specific type.

        Args:
            component_type: The type of the components to retrieve
            namespace: Return only this agent's components; ``None`` returns every namespace.

        Returns:
            A list of component names
        """

        return [
            name
            for name, component in self._components.items()
            if isinstance(component, component_type) and (namespace is None or namespace_of(component) == namespace)
        ]

    def has_component(self, name_or_class: str | Any, namespace: str | None = None) -> bool:
        """Check if a component is registered.

        Args:
            name_or_class: Name of the component or class, that inherits from Component
            namespace: Look in this agent, then the root, for a name; for a class, look only in
                this agent. ``None`` looks everywhere.

        Returns:
            True if component is registered, False otherwise
        """

        if isinstance(name_or_class, str):
            return self._lookup(name_or_class, namespace) is not None
        return bool(self.get_components_by_type(name_or_class, namespace))

    def has_component_of_type(self, component_type: Any, name: str | None = None, namespace: str | None = None) -> bool:
        """Check if a component is registered.

        Args:
            component_type: Type of the component
            name: Name of the component (optional)
            namespace: Restrict the question to this agent; ``None`` asks about every namespace.

        Returns:
            True if component is registered, False otherwise
        """

        if name is not None:
            component = self._lookup(name, namespace)
            if component is None:
                raise ValueError(f"No component with name {name} registered")
            if not isinstance(component, component_type):
                raise ValueError(f"Component with name {name} is not of type {component_type}")
            return True
        return bool(self.get_components_by_type(component_type, namespace))

    def clear_components(self) -> None:
        """Clear all registered components (useful for testing)."""

        logger.info("Clearing all registered components")
        self._components.clear()

    def clear(self) -> None:
        """
        Clear all registered components.

        Useful for testing or resetting the registry state.
        """

        logger.info("Clearing all components from registry")
        self.clear_components()
        if self._cache_service is not None:
            self._cache_service.clear()
            self._cache_service = None

    def has_cache(self) -> bool:
        """Check if a cache service is registered.

        Returns:
            True if cache service is registered, False otherwise
        """

        return self._cache_service is not None

    def has_event_handler(self, name: str | None = None, namespace: str | None = None) -> bool:
        """Check if a handler is registered.

        Args:
            name: Name of the handler (optional)

        Returns:
            True if handler is registered, False otherwise
        """

        return self.has_component_of_type(EventHandlerBase, name, namespace)

    def get_event_handler(self, namespace: str | None = None) -> list[EventHandlerBase]:
        """Get all registered handlers.

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(EventHandlerBase, namespace)

    def has_agents(self, name: str | None = None, namespace: str | None = None) -> bool:
        """Check if an agent is registered.

        Args:
            name: Name of the agent (optional)

        Returns:
            True if at least one agent is registered, False otherwise
        """

        return self.has_component_of_type(AgentRuntime, name, namespace)

    def get_agent(self, name: str, namespace: str | None = None) -> AgentRuntime:
        """Get a registered agent by name.

        Args:
            name: Name of the agent
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The AgentRuntime instance

        Raises:
            ValueError: If no agent with that name is registered or the component is not an AgentRuntime
        """

        component = self.get_component(name, namespace)
        if not isinstance(component, AgentRuntime):
            raise ValueError(f"Component '{name}' is not an AgentRuntime")
        return component

    def get_agents(self, namespace: str | None = None) -> list[str]:
        """Get list of all registered agent names.

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_component_names_by_type(AgentRuntime, namespace)

    def has_rest_apis(self, name: str | None = None, namespace: str | None = None) -> bool:
        """Check if a REST API is registered.

        Args:
            name: Name of the REST API (optional)

        Returns:
            True if REST API is registered, False otherwise
        """

        return self.has_component_of_type(RestApiBase, name, namespace)

    def get_rest_api_names(self, namespace: str | None = None) -> list[str]:
        """Get list of all registered REST API names.

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_component_names_by_type(RestApiBase, namespace)

    def get_rest_api(self, name_or_class: str | type[RestApiBase], namespace: str | None = None) -> RestApiBase:
        """Get a registered REST API by name or class.

        Args:
            name_or_class: Name string or concrete REST API class
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The RestApiBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, RestApiBase, namespace)  # type: ignore[type-abstract]

    def get_rest_apis(self, namespace: str | None = None) -> list[RestApiBase]:
        """Get all registered REST APIs.

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(RestApiBase, namespace)

    def has_services(self, name: str | None = None, namespace: str | None = None) -> bool:
        """Check if a business service is registered.

        Args:
            name: Name of the business service (optional)

        Returns:
            True if business service is registered, False otherwise
        """

        return self.has_component_of_type(ServiceBase, name, namespace)

    def get_service(self, name_or_class: str | type[ServiceT], namespace: str | None = None) -> ServiceT:
        """Get a registered service by name or class.

        Args:
            name_or_class: Name string or concrete service class
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The ServiceBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, ServiceBase, namespace)  # type: ignore

    def get_services(self, namespace: str | None = None) -> list[ServiceBase]:
        """Get all registered business services.

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(ServiceBase, namespace)

    def has_schedulers(self, name: str | None = None, namespace: str | None = None) -> bool:
        """Check if a scheduler is registered.

        Args:
            name: Name of the scheduler (optional)

        Returns:
            True if scheduler is registered, False otherwise
        """

        return self.has_component_of_type(SchedulerBase, name, namespace)

    def get_scheduler(self, name_or_class: str | type[SchedulerBase], namespace: str | None = None) -> SchedulerBase:
        """Get a registered scheduler by name or class.

        Args:
            name_or_class: Name string or concrete scheduler class
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The SchedulerBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, SchedulerBase, namespace)  # type: ignore[type-abstract]

    def get_schedulers(self, namespace: str | None = None) -> list[SchedulerBase]:
        """Get all registered schedulers.

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(SchedulerBase, namespace)

    def get_client(self, name_or_class: str | type[ClientBase], namespace: str | None = None) -> ClientBase:
        """Get a registered client by name or class.

        Args:
            name_or_class: Name string or concrete client class
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The ClientBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, ClientBase, namespace)  # type: ignore[type-abstract]

    def get_io_client(self, name_or_class: str | type[IOClientBase], namespace: str | None = None) -> IOClientBase:
        """Get a registered IO client by name or class.

        Args:
            name_or_class: Name string or concrete IO client class
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The IOClientBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, IOClientBase, namespace)  # type: ignore[type-abstract]

    def get_ai_client(self, name_or_class: str | type[AIClientBase], namespace: str | None = None) -> AIClientBase:
        """Get a registered AI client by name or class.

        Args:
            name_or_class: Name string or concrete AI client class
            namespace: Resolve for this agent -- its own first, then the root one.

        Returns:
            The AIClientBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, AIClientBase, namespace)  # type: ignore[type-abstract]

    def get_clients(self, namespace: str | None = None) -> list[ClientBase]:
        """Get all registered clients (IO and AI).

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(ClientBase, namespace)

    def get_io_clients(self, namespace: str | None = None) -> list[IOClientBase]:
        """Get all registered IO transport clients (Dapr, NATS, etc.).

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(IOClientBase, namespace)

    def get_ai_clients(self, namespace: str | None = None) -> list[AIClientBase]:
        """Get all registered AI provider clients (vLLM, OpenAI, etc.).

        Args:
            namespace: Restrict to this agent; ``None`` (the default) is every namespace.
        """

        return self.get_components_by_type(AIClientBase, namespace)
