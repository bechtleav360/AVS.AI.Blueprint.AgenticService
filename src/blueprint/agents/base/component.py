"""Abstract base class for all framework components.

This module provides the common interface that all framework components
(EventHandler, BusinessService, AgentRuntime, RestApi, Scheduler) implement.

Concrete default implementations are provided for all lifecycle and dependency
injection methods. Subclasses only need to override what is domain-specific.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..config import Config
from ..utils import camel_to_snake

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

    Every Component will by default have its name set to its class name.
    """

    _registry = ComponentRegistry()
    _config: Config | None = None

    def __init__(self, should_register:bool = True) -> None:
        """Initialize the component.
        """

        self._name = camel_to_snake(self.__class__.__name__)
        if should_register:
            self.registry.add_component(self.name, self)

    @property
    def name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        return self._name

    @name.setter
    def name(self, value: str):
        """Set the component name. Also updates the name in the component registry.

        Args:
            value: The component name
        """

        self.registry.update_component_name(self._name, value)
        self._name = value

    @property
    def registry(self) -> ComponentRegistry:
        """Get the component registry for accessing other components.

        Uses class-level variable to avoid shadowing the registry.

        Returns:
            The ComponentRegistry instance
        """

        return Component._registry

    @property
    def config(self) -> Config:
        """Get the configuration linked to this component.

        Returns:
            The Config instance linked via dependency injection
        """

        return Component._config

    @config.setter
    def config(self, value: Config):
        """Set the configuration linked to this component.

        Args:
            value: The Config instance
        """

        Component._config = value

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        return self._name

    def get_registry(self) -> ComponentRegistry:
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if self._registry is None:
            raise RuntimeError(f"Component registry not linked to component '{self._name}'")
        return self._registry

    def get_config(self) -> Config:
        """Get the configuration linked to this component.

        Returns:
            The Config instance linked via dependency injection

        Raises:
            RuntimeError: If config is not wired
        """
        if self._config is None:
            raise RuntimeError(f"Config not linked to component '{self._name}'")
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
        self._registry = registry

    @abstractmethod
    async def on_startup(self) -> None:
        """Called when component is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """

        raise NotImplementedError()

    @abstractmethod
    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """

        raise NotImplementedError()
