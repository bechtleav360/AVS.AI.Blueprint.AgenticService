"""Abstract base class for all framework components.

This module provides the common interface that all framework components
(EventHandler, BusinessService, AgentRuntime, RestApi, Scheduler) implement.

Concrete default implementations are provided for all lifecycle and dependency
injection methods. Subclasses only need to override what is domain-specific.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from ..config import Config

if TYPE_CHECKING:
    from ..registry.component_registry import ComponentRegistry


class Component(ABC):
    """Abstract base class for all framework components.

    Provides concrete default implementations for the common lifecycle and
    dependency injection interface. Subclasses inherit these and only override
    what is specific to their domain:

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

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        return self._component_name

    def get_registry(self) -> ComponentRegistry:
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if self._component_registry is None:
            raise RuntimeError(f"Component registry not linked to component '{self._component_name}'")
        return self._component_registry

    def get_config(self) -> Config:
        """Get the configuration linked to this component.

        Returns:
            The Config instance linked via dependency injection

        Raises:
            RuntimeError: If config is not wired
        """
        if self._config is None:
            raise RuntimeError(f"Config not linked to component '{self._component_name}'")
        return self._config

    def link_config(self, config: Config) -> None:
        """Link configuration to the component via dependency injection.

        Args:
            config: The Config instance
        """
        self._config = config

    def link_component_registry(self, registry: ComponentRegistry) -> None:
        """Link the component registry to the component.

        Args:
            registry: The ComponentRegistry instance
        """
        self._component_registry = registry

    async def on_startup(self) -> None:
        """Called when component is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """

    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """
