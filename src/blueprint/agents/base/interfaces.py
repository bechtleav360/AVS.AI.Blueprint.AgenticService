"""Interface definitions for framework components.

These interfaces define the contract that all components must follow.
They use Protocol pattern (similar to Java interfaces) to define expected methods
without enforcing inheritance.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..config import Config

if TYPE_CHECKING:
    from ..registry.component_registry import ComponentRegistry


@runtime_checkable
class ComponentInterface(Protocol):
    """Interface that all framework components must implement.

    Components are expected to have:
    - A name attribute
    - A get_registry() method to access the component registry
    - Optional lifecycle methods (on_startup, on_shutdown)

    This is similar to a Java interface - it defines the contract
    without enforcing inheritance.
    """

    name: str
    """Service name - unique identifier for the service."""

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        ...

    def get_config(self) -> Config:
        """Get the component configuration.

        Returns:
            The Config instance linked to this component

        Raises:
            RuntimeError: If config is not wired
        """

        ...

    def get_registry(self) -> "ComponentRegistry":
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        ...

    def link_component_registry(self, registry: "ComponentRegistry") -> None:
        """Link the component registry to the handler."""

        ...

    def link_config(self, config: Config) -> None:
        """Adds config via dependency injection, so that handlers can access environment variables during runtime"""

        ...

    async def on_startup(self) -> None:
        """Called when service is registered and wired."""
        ...

    async def on_shutdown(self) -> None:
        """Called when application is shutting down."""
        ...
