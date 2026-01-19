"""Abstract base class for all framework components.

This module provides the common interface that all framework components
(EventHandler, BusinessService, AgentRuntime, RestApi) implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..config import Config

if TYPE_CHECKING:
    from ..registry.component_registry import ComponentRegistry


class Component(ABC):
    """Abstract base class for all framework components.

    Defines the common lifecycle and dependency injection interface that all
    framework components must implement. This includes:
    - Component naming and identification
    - Access to configuration and component registry
    - Lifecycle hooks for startup and shutdown
    """

    def __init__(self, name: str = "Component") -> None:
        """Initialize the component.

        Args:
            name: Human-readable name for the component
        """
        self._component_name = name
        self._config: Config | None = None
        self._component_registry: ComponentRegistry | None = None

    @abstractmethod
    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        raise NotImplementedError

    @abstractmethod
    def get_registry(self) -> ComponentRegistry:
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        raise NotImplementedError

    @abstractmethod
    def get_config(self) -> Config:
        """Get the configuration linked to this component.

        Returns:
            The Config instance linked via dependency injection

        Raises:
            RuntimeError: If config is not wired
        """
        raise NotImplementedError

    @abstractmethod
    def link_config(self, config: Config) -> None:
        """Link configuration to the component via dependency injection.

        This allows components to access environment variables and configuration
        during runtime.

        Args:
            config: The Config instance
        """
        raise NotImplementedError

    @abstractmethod
    def link_component_registry(self, registry: ComponentRegistry) -> None:
        """Link the component registry to the component.

        This allows components to access other components via the registry.

        Args:
            registry: The ComponentRegistry instance
        """
        raise NotImplementedError

    @abstractmethod
    async def on_startup(self) -> None:
        """Called when component is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """
        raise NotImplementedError

    @abstractmethod
    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """
        raise NotImplementedError
