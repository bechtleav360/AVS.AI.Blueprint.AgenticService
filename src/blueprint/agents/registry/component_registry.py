"""Unified registry for managing all application components.

This registry consolidates handler, runtime, and agent management into a single
component without containing business logic. Business logic remains in
ProcessingService.
"""

import logging
from typing import Any, TypeVar, overload

from blueprint.agents.services.event_publishing_service import EventPublishingService
from blueprint.agents.services.processing_service import ProcessingService

from blueprint.agents.base.agent_runtime import AgentRuntime
from blueprint.agents.base.business_service import BusinessService
from blueprint.agents.base.event_handler import EventHandler
from blueprint.agents.base.rest_api import RestApi
from blueprint.agents.config import Config


logger = logging.getLogger(__name__)

T = TypeVar("T")


class ComponentRegistry:
    """
    Unified registry for managing handlers and runtimes.

    This class is responsible ONLY for:
    - Storing and organizing components (handlers, runtimes)
    - Providing access to registered components
    - Managing component lifecycle (registration, retrieval)

    Business logic (event processing, orchestration) belongs in ProcessingService.
    """

    def __init__(self, settings: Config) -> None:
        """
        Initialize the component registry.

        Args:
            settings: Application configuration
        """
        self._settings = settings

        self._processing_service: Any | None = None
        self._event_publishing_service: Any | None = None
        self._agents: dict[str, AgentRuntime] = {}
        self._rest_apis: dict[str, RestApi] = {}
        self._business_services: dict[str, BusinessService] = {}
        self._handlers: list[EventHandler] = []

        logger.info("ComponentRegistry initialized")

    # ========================================================================
    # Handler Management
    # ========================================================================

    def register_handler(self, handler: "EventHandler") -> None:
        """
        Register a single event handler.

        Args:
            handler: The handler instance to register
        """
        logger.info("Registering handler: %s with priority %d", handler._name, handler._priority)

        handler.link_config(self._settings)
        handler.link_component_registry(self)

        self._handlers.append(handler)

    def get_handlers(self) -> list["EventHandler"]:
        """
        Get all registered handlers, sorted by priority.

        Returns:
            List of handler instances sorted by priority (may be empty)
        """
        handlers = sorted(self._handlers, key=lambda x: x._priority)
        return handlers

    def has_handler(self, name: str = None) -> bool:
        """Check if a handler is registered.

        Args:
            name: Name of the handler (optional)

        Returns:
            True if handler is registered, False otherwise
        """
        if name is None:
            return len(self._handlers) > 0

        return any(h.get_name() == name for h in self._handlers)

    def clear_handlers(self) -> None:
        """Clear all registered handlers (useful for testing)."""
        logger.info("Clearing all registered handlers")
        self._handlers.clear()

    # ========================================================================
    # General Management
    # ========================================================================

    def clear(self) -> None:
        """
        Clear all registered components.

        Useful for testing or resetting the registry state.
        """
        logger.info("Clearing all components from registry")
        self.clear_handlers()
        self._agents.clear()
        self._rest_apis.clear()
        self._business_services.clear()

    def get_settings(self) -> Config:
        """
        Get the application settings.

        Returns:
            Application configuration
        """
        return self._settings

    # ========================================================================
    # ProcessingService Management
    # ========================================================================

    def register_processing_service(self, processing_service: ProcessingService) -> None:
        """
        Register the processing service instance.

        Args:
            processing_service: The ProcessingService instance
        """
        logger.info("Registering processing service")
        self._processing_service = processing_service

    def get_processing_service(self) -> ProcessingService:
        """
        Get the registered processing service.

        Returns:
            The ProcessingService instance

        Raises:
            ValueError: If no processing service is registered
        """
        if self._processing_service is None:
            error_msg = "No processing service registered"
            logger.error(error_msg)
            raise ValueError(error_msg)
        return self._processing_service

    # ========================================================================
    # EventPublishingService Management
    # ========================================================================

    def register_event_publishing_service(self, event_publishing_service: EventPublishingService) -> None:
        """
        Register the event publishing service instance.

        Args:
            event_publishing_service: The EventPublishingService instance
        """
        logger.info("Registering event publishing service")

        self._event_publishing_service = event_publishing_service

    def get_event_publishing_service(self) -> EventPublishingService:
        """
        Get the registered event publishing service.

        Returns:
            The EventPublishingService instance

        Raises:
            ValueError: If no event publishing service is registered
        """
        if self._event_publishing_service is None:
            error_msg = "No event publishing service registered"
            logger.error(error_msg)
            raise ValueError(error_msg)
        return self._event_publishing_service

    # ========================================================================
    # Agent Management
    # ========================================================================

    def register_agent(self, agent: "AgentRuntime") -> None:
        """Register an agent with a name.

        Args:
            agent: Configured Agent instance

        Raises:
            ValueError: If agent with this name already exists
        """
        if agent.get_name() in self._agents:
            raise ValueError(f"Agent '{agent.get_name()}' is already registered")

        agent.link_config(self._settings)
        agent.link_component_registry(self)

        self._agents[agent.get_name()] = agent
        logger.info("Registered agent: %s", agent.get_name())

    @overload
    def get_agent(self, name: str) -> "AgentRuntime": ...

    @overload
    def get_agent(self, name: type[T]) -> T: ...

    def get_agent(self, name: str | type[T]) -> "AgentRuntime | T":
        """Get a registered agent by name or class type.

        Args:
            name: Name of the agent (str) or the agent class (type)

        Returns:
            The registered Agent instance.
            If a class is provided, returns the instance of that class with correct type hint.

        Raises:
            ValueError: If agent not found
        """
        if isinstance(name, str):
            if name not in self._agents:
                available = ", ".join(self._agents.keys()) if self._agents else "none"
                raise ValueError(f"Agent '{name}' not found. Available agents: {available}")
            return self._agents[name]

        for agent in self._agents.values():
            if isinstance(agent, name):
                return agent

        available = ", ".join(type(a).__name__ for a in self._agents.values()) if self._agents else "none"
        raise ValueError(f"Agent of type '{name.__name__}' not found. Available types: {available}")

    def has_agent(self, name: str = None) -> bool:
        """Check if an agent is registered.

        Args:
            name: Name of the agent

        Returns:
            True if agent is registered, False otherwise
        """
        if name is None:
            return len(self._agents) > 0

        return name in self._agents

    def list_agents(self) -> list[str]:
        """Get list of all registered agent names.

        Returns:
            List of agent names
        """
        return list(self._agents.keys())

    def get_agent_registry(self):
        """Get the agent registry (for backward compatibility).

        Returns:
            Self (ComponentRegistry acts as agent registry)
        """
        return self

    # ========================================================================
    # REST API Management
    # ========================================================================

    def register_rest_api(self, api: "RestApi") -> None:
        """Register a REST API instance.

        Args:
            api: The RestApi instance to register

        Raises:
            ValueError: If REST API with this name already exists
        """
        if api.get_name() in self._rest_apis:
            raise ValueError(f"REST API '{api.get_name()}' is already registered")

        api.link_component_registry(self)
        api.link_config(self._settings)

        self._rest_apis[api.get_name()] = api
        logger.info("Registered REST API: %s", api.get_name())

    @overload
    def get_rest_api(self, name: str) -> "RestApi": ...

    @overload
    def get_rest_api(self, name: type[T]) -> T: ...

    def get_rest_api(self, name: str | type[T]) -> "RestApi | T":
        """Get a registered REST API by name or class type.

        Args:
            name: Name of the REST API (str) or the REST API class (type)

        Returns:
            The registered RestApi instance.
            If a class is provided, returns the instance of that class with correct type hint.

        Raises:
            ValueError: If REST API not found
        """
        if isinstance(name, str):
            if name not in self._rest_apis:
                available = ", ".join(self._rest_apis.keys()) if self._rest_apis else "none"
                raise ValueError(f"REST API '{name}' not found. Available APIs: {available}")
            return self._rest_apis[name]

        for api in self._rest_apis.values():
            if isinstance(api, name):
                return api

        available = ", ".join(type(a).__name__ for a in self._rest_apis.values()) if self._rest_apis else "none"
        raise ValueError(f"REST API of type '{name.__name__}' not found. Available types: {available}")

    def has_rest_api(self, name: str = None) -> bool:
        """Check if a REST API is registered.

        Args:
            name: Name of the REST API

        Returns:
            True if REST API is registered, False otherwise
        """
        if name is None:
            return len(self._rest_apis) > 0

        return name in self._rest_apis

    def list_rest_apis(self) -> list[str]:
        """Get list of all registered REST API names.

        Returns:
            List of REST API names
        """
        return list(self._rest_apis.keys())

    def get_rest_apis(self) -> list["RestApi"]:
        """Get all registered REST APIs.

        Returns:
            Copy of the REST APIs list (may be empty)
        """
        return list(self._rest_apis.values())

    # ========================================================================
    # Business Service Management
    # ========================================================================

    def register_service(self, service: "BusinessService") -> None:
        """Register a business service instance.

        Args:
            service: The BusinessService instance to register

        Raises:
            ValueError: If business service with this name already exists
        """
        if service.get_name() in self._business_services:
            raise ValueError(f"Business service '{service.get_name()}' is already registered")

        service.link_config(self._settings)
        service.link_component_registry(self)

        self._business_services[service.get_name()] = service
        logger.info("Registered business service: %s", service.get_name())

    @overload
    def get_service(self, name: str) -> "BusinessService": ...

    @overload
    def get_service(self, name: type[T]) -> T: ...

    def get_service(self, name: str | type[T]) -> "BusinessService | T":
        """Get a registered business service by name or class type.

        Args:
            name: Name of the business service (str) or the service class (type)

        Returns:
            The registered BusinessService instance.
            If a class is provided, returns the instance of that class with correct type hint.

        Raises:
            ValueError: If business service not found
        """
        if isinstance(name, str):
            if name not in self._business_services:
                available = ", ".join(self._business_services.keys()) if self._business_services else "none"
                raise ValueError(f"Business service '{name}' not found. Available services: {available}")
            return self._business_services[name]

        for service in self._business_services.values():
            if isinstance(service, name):
                return service

        # Fallback: match by class name to support reloaded modules or duplicate class definitions
        requested_type_name = getattr(name, "__name__", str(name))
        matching_services = [service for service in self._business_services.values() if type(service).__name__ == requested_type_name]

        if len(matching_services) == 1:
            logger.warning(
                "Business service lookup for type '%s' matched by class name. "
                "Ensure services share a single class definition to avoid ambiguity.",
                requested_type_name,
            )
            return matching_services[0]
        if len(matching_services) > 1:
            logger.error(
                "Multiple business services share the class name '%s'. Available matches: %s",
                requested_type_name,
                ", ".join(service.get_name() for service in matching_services),
            )
            conflicts = ", ".join(service.get_name() for service in matching_services)
            raise ValueError(
                "Multiple business services share the requested type name. "
                f"Please disambiguate by passing the service name. Conflicts: {conflicts}"
            )

        available = ", ".join(type(s).__name__ for s in self._business_services.values()) if self._business_services else "none"
        raise ValueError(f"Business service of type '{requested_type_name}' not found. Available types: {available}")

    def has_service(self, name: str) -> bool:
        """Check if a business service is registered.

        Args:
            name: Name of the business service

        Returns:
            True if business service is registered, False otherwise
        """
        if not name:
            return len(self._business_services) > 0

        return name in self._business_services

    def list_services(self) -> list["BusinessService"]:
        """Get all registered business services.

        Returns:
            Copy of the business services list (may be empty)
        """
        return list(self._business_services.values())
