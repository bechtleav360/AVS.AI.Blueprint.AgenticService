from abc import ABC
from typing import TYPE_CHECKING, Any

from ..config import Config

if TYPE_CHECKING:
    from ..registry.component_registry import ComponentRegistry


class BusinessService(ABC):
    """Abstract base class for business services.

    Implements ComponentInterface to provide consistent lifecycle and registry access.
    """

    def __init__(self, name: str = "BusinessService") -> None:
        """Initialize the business service.

        Args:
            name: Human-readable name for the service
        """
        self._name = name
        self._component_registry: Any = None
        self._config: Config | None = None

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        return self._name

    def get_registry(self) -> "ComponentRegistry":
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if not hasattr(self, "_component_registry") or self._component_registry is None:
            raise RuntimeError(f"Component registry not linked to service '{self._name}'")
        return self._component_registry

    def get_config(self) -> Config:
        """Get the configuration linked to this service.

        Returns:
            The Config instance linked via dependency injection

        Raises:
            RuntimeError: If config is not wired
        """

        if self._config is None:
            raise RuntimeError(f"Config not linked to service '{self._name}'")
        return self._config

    def link_component_registry(self, registry: "ComponentRegistry") -> None:
        """Link the component registry to the service.

        This allows services to access other components via the registry.

        Args:
            registry: The ComponentRegistry instance
        """
        self._component_registry = registry

    def link_config(self, config: Config) -> None:
        """Link configuration to the service via dependency injection.

        This allows services to access environment variables and configuration
        during runtime.

        Args:
            config: The Config instance
        """
        self._config = config

    async def on_startup(self) -> None:
        """Called when service is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """
        pass

    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """
        pass
