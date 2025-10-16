"""Unified registry for managing all application components.

This registry consolidates handler and runtime management into a single
component without containing business logic. Business logic remains in
ProcessingService.
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..config import Config

if TYPE_CHECKING:  # pragma: no cover
    from ..agent import BaseAgent, EventHandler

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
        self._runtimes: Dict[str, "BaseAgent"] = {}
        self._default_runtime: Optional[str] = None
        self._processing_service: Optional[Any] = None
        self._event_publishing_service: Optional[Any] = None
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
    # Runtime Management
    # ========================================================================

    def register_runtime(
        self, name: str, runtime: "BaseAgent", is_default: bool = False
    ) -> None:
        """
        Register an agent runtime.
        
        Args:
            name: Unique name for the runtime
            runtime: The runtime instance to register
            is_default: Whether this should be the default runtime
        """
        logger.info("Registering runtime: %s", name)
        self._runtimes[name] = runtime

        if is_default or self._default_runtime is None:
            self._default_runtime = name
            logger.info("Set %s as default runtime", name)

        # Link registry to runtime
        runtime.link_service_registry(self)

    def get_runtime(self, name: Optional[str] = None) -> Optional["BaseAgent"]:
        """
        Get a specific runtime by name, or the default runtime.
        
        Args:
            name: Name of the runtime to retrieve, or None for default
            
        Returns:
            The requested runtime, or None if not found
        """
        if name is None:
            name = self._default_runtime

        if name is None:
            logger.warning("No default runtime set and no name provided")
            return None

        runtime = self._runtimes.get(name)
        if runtime is None:
            logger.warning("Runtime %s not found", name)

        return runtime

    def get_all_runtimes(self) -> Dict[str, "BaseAgent"]:
        """
        Get all registered runtimes.
        
        Returns:
            Dictionary of runtime name to runtime instance
        """
        return self._runtimes.copy()

    def get_default_runtime_name(self) -> Optional[str]:
        """
        Get the name of the default runtime.
        
        Returns:
            Name of the default runtime, or None if not set
        """
        return self._default_runtime

    def clear_runtimes(self) -> None:
        """Clear all registered runtimes (useful for testing)."""
        logger.info("Clearing all registered runtimes")
        self._runtimes.clear()
        self._default_runtime = None

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
        self.clear_runtimes()

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
