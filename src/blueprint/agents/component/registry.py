"""Unified registry for managing all application components.

This registry consolidates handler, runtime, and agent management into a single
component without containing business logic. Business logic remains in
ProcessingService.
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

    def _resolve_single(self, name_or_class: str | type[T], base_type: type[T]) -> T:
        """Resolve a single component by name string or concrete class.

        Resolution order when a class is passed:
        1. Look up camel_to_snake(ClassName) in the registry.
        2. If not found, collect all instances of that class.
           - Exactly one → return it.
           - Zero or many → raise ValueError.
        """
        if not isinstance(name_or_class, str):
            snake_name = camel_to_snake(name_or_class.__name__)
            if snake_name in self._components:
                name_or_class = snake_name  # fall through to string lookup below
            # else: pass the class to get_component for type-scan

        component = self.get_component(name_or_class)
        if not isinstance(component, base_type):
            raise ValueError(f"Component '{name_or_class}' is not a {base_type.__name__}")
        return component

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

    def get_component(self, name_or_class: str | Any) -> Any:
        """Get a component from the registry.

        Args:
            name_or_class: Name of the component or class, that inherits from Component

        Returns:
            An instance of a Component class
        """

        if not isinstance(name_or_class, str):
            candidates = [name for name, component in self._components.items() if isinstance(component, name_or_class)]
            if len(candidates) == 0:
                raise ValueError(f"No components of type {name_or_class} found")
            if len(candidates) == 1:
                name_or_class = candidates[0]
            if len(candidates) > 1:
                raise ValueError(f"Multiple components of type {name_or_class} found: {candidates}")
        elif name_or_class not in self._components:
            raise ValueError(f"Component with name {name_or_class} does not exist")

        return self._components[name_or_class]

    def get_components_by_type(self, component_type: Any) -> list[Any]:  #
        """Get all components from the registry of a specific type.

        Args:
            component_type: The type of the components to retrieve

        Returns:
            A list of components
        """

        return [component for component in self._components.values() if isinstance(component, component_type)]

    def get_component_names_by_type(self, component_type: Any) -> list[str]:  #
        """Get all component names from the registry of a specific type.

        Args:
            component_type: The type of the components to retrieve

        Returns:
            A list of component names
        """

        return [name for name, component in self._components.items() if isinstance(component, component_type)]

    def has_component(self, name_or_class: str | Any) -> bool:
        """Check if a component is registered.

        Args:
            name_or_class: Name of the component or class, that inherits from Component

        Returns:
            True if component is registered, False otherwise
        """

        if isinstance(name_or_class, str):
            return name_or_class in self._components
        else:
            return any(isinstance(component, name_or_class) for component in self._components.values())

    def has_component_of_type(self, component_type: Any, name: str | None = None) -> bool:
        """Check if a component is registered.

        Args:
            component_type: Type of the component
            name: Name of the component (optional)

        Returns:
            True if component is registered, False otherwise
        """

        if name is not None:
            if name in self._components:
                if not isinstance(self._components[name], component_type):
                    raise ValueError(f"Component with name {name} is not of type {component_type}")
                else:
                    return True
            else:
                raise ValueError(f"No component with name {name} registered")
        else:
            return any(isinstance(component, component_type) for component in self._components.values())

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

    def has_event_handler(self, name: str | None = None) -> bool:
        """Check if a handler is registered.

        Args:
            name: Name of the handler (optional)

        Returns:
            True if handler is registered, False otherwise
        """

        return self.has_component_of_type(EventHandlerBase, name)

    def get_event_handler(self) -> list[EventHandlerBase]:
        """Get all registered handlers."""

        return self.get_components_by_type(EventHandlerBase)

    def has_agents(self, name: str | None = None) -> bool:
        """Check if an agent is registered.

        Args:
            name: Name of the agent (optional)

        Returns:
            True if at least one agent is registered, False otherwise
        """

        return self.has_component_of_type(AgentRuntime, name)

    def get_agent(self, name: str) -> AgentRuntime:
        """Get a registered agent by name.

        Args:
            name: Name of the agent

        Returns:
            The AgentRuntime instance

        Raises:
            ValueError: If no agent with that name is registered or the component is not an AgentRuntime
        """

        component = self.get_component(name)
        if not isinstance(component, AgentRuntime):
            raise ValueError(f"Component '{name}' is not an AgentRuntime")
        return component

    def get_agents(self) -> list[str]:
        """Get list of all registered agent names."""

        return self.get_component_names_by_type(AgentRuntime)

    def has_rest_apis(self, name: str | None = None) -> bool:
        """Check if a REST API is registered.

        Args:
            name: Name of the REST API (optional)

        Returns:
            True if REST API is registered, False otherwise
        """

        return self.has_component_of_type(RestApiBase, name)

    def get_rest_api_names(self) -> list[str]:
        """Get list of all registered REST API names."""

        return self.get_component_names_by_type(RestApiBase)

    def get_rest_api(self, name_or_class: str | type[RestApiBase]) -> RestApiBase:
        """Get a registered REST API by name or class.

        Args:
            name_or_class: Name string or concrete REST API class

        Returns:
            The RestApiBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, RestApiBase)  # type: ignore[type-abstract]

    def get_rest_apis(self) -> list[RestApiBase]:
        """Get all registered REST APIs."""

        return self.get_components_by_type(RestApiBase)

    def has_services(self, name: str | None = None) -> bool:
        """Check if a business service is registered.

        Args:
            name: Name of the business service (optional)

        Returns:
            True if business service is registered, False otherwise
        """

        return self.has_component_of_type(ServiceBase, name)

    def get_service(self, name_or_class: str | type[ServiceBase]) -> ServiceBase:
        """Get a registered service by name or class.

        Args:
            name_or_class: Name string or concrete service class

        Returns:
            The ServiceBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, ServiceBase)  # type: ignore[type-abstract]

    def get_services(self) -> list[ServiceBase]:
        """Get all registered business services."""

        return self.get_components_by_type(ServiceBase)

    def has_schedulers(self, name: str | None = None) -> bool:
        """Check if a scheduler is registered.

        Args:
            name: Name of the scheduler (optional)

        Returns:
            True if scheduler is registered, False otherwise
        """

        return self.has_component_of_type(SchedulerBase, name)

    def get_scheduler(self, name_or_class: str | type[SchedulerBase]) -> SchedulerBase:
        """Get a registered scheduler by name or class.

        Args:
            name_or_class: Name string or concrete scheduler class

        Returns:
            The SchedulerBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, SchedulerBase)  # type: ignore[type-abstract]

    def get_schedulers(self) -> list[SchedulerBase]:
        """Get all registered schedulers."""

        return self.get_components_by_type(SchedulerBase)

    def get_client(self, name_or_class: str | type[ClientBase]) -> ClientBase:
        """Get a registered client by name or class.

        Args:
            name_or_class: Name string or concrete client class

        Returns:
            The ClientBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, ClientBase)  # type: ignore[type-abstract]

    def get_io_client(self, name_or_class: str | type[IOClientBase]) -> IOClientBase:
        """Get a registered IO client by name or class.

        Args:
            name_or_class: Name string or concrete IO client class

        Returns:
            The IOClientBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, IOClientBase)  # type: ignore[type-abstract]

    def get_ai_client(self, name_or_class: str | type[AIClientBase]) -> AIClientBase:
        """Get a registered AI client by name or class.

        Args:
            name_or_class: Name string or concrete AI client class

        Returns:
            The AIClientBase instance

        Raises:
            ValueError: If not found, wrong type, or multiple matches exist
        """

        return self._resolve_single(name_or_class, AIClientBase)  # type: ignore[type-abstract]

    def get_clients(self) -> list[ClientBase]:
        """Get all registered clients (IO and AI)."""

        return self.get_components_by_type(ClientBase)

    def get_io_clients(self) -> list[IOClientBase]:
        """Get all registered IO transport clients (Dapr, NATS, etc.)."""

        return self.get_components_by_type(IOClientBase)

    def get_ai_clients(self) -> list[AIClientBase]:
        """Get all registered AI provider clients (vLLM, OpenAI, etc.)."""

        return self.get_components_by_type(AIClientBase)
