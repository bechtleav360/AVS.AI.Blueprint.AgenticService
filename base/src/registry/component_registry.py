"""Unified registry for managing all application components.

This registry consolidates handler and runtime management into a single
component without containing business logic. Business logic remains in
ProcessingService.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..config import Config

if TYPE_CHECKING:  # pragma: no cover
    from ..handler import EventHandler

logger = logging.getLogger(__name__)


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
        self._handlers: List["EventHandler"] = []
        self._processing_service: Optional[Any] = None
        self._event_publishing_service: Optional[Any] = None

        # Import here to avoid circular dependency
        from .agent_registry import AgentRegistry

        self._agent_registry = AgentRegistry()

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
        logger.info(
            "Registering handler: %s with priority %d", handler.name, handler.priority
        )
        handler.link_service_registry(self)
        handler.link_component_registry(self)  # Inject component registry
        self._handlers.append(handler)
        # Keep handlers sorted by priority (lower numbers first)
        self._handlers.sort()

    def register_handlers(self, handlers: List["EventHandler"]) -> None:
        """
        Register multiple event handlers.

        Args:
            handlers: List of handler instances to register
        """
        for handler in handlers:
            self.register_handler(handler)

    def get_handlers(self) -> List["EventHandler"]:
        """
        Get all registered handlers, sorted by priority.

        Returns:
            Copy of the handlers list
        """
        return self._handlers.copy()

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
        self._agent_registry.clear()

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

    def register_processing_service(self, processing_service: Any) -> None:
        """
        Register the processing service instance.

        Args:
            processing_service: The ProcessingService instance
        """
        logger.info("Registering processing service")
        self._processing_service = processing_service

    def get_processing_service(self) -> Any:
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

    def register_event_publishing_service(self, event_publishing_service: Any) -> None:
        """
        Register the event publishing service instance.

        Args:
            event_publishing_service: The EventPublishingService instance
        """
        logger.info("Registering event publishing service")
        self._event_publishing_service = event_publishing_service

    def get_event_publishing_service(self) -> Any:
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
    # AgentRegistry Management
    # ========================================================================

    def get_agent_registry(self):
        """
        Get the agent registry for managing configured agents.

        Returns:
            The AgentRegistry instance
        """
        return self._agent_registry
