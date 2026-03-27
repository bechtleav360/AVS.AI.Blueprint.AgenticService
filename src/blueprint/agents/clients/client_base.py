"""Base class for eventing clients providing common interface for messaging systems."""

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING
from collections.abc import Awaitable, Callable

from ..component.component import Component
from ..models.events import CloudEvent

if TYPE_CHECKING:
    from ..io.api.actuators.health.health_base import ComponentHealth


class ClientBase(Component, ABC):
    """Abstract base class for all clients (IO transports, AI providers).

    Extends Component so that all clients:
    - Auto-register in the component registry on instantiation
    - Participate in the application lifecycle via on_startup/on_shutdown
    - Are discoverable for health checking

    Subclasses must NOT access self.config in __init__. Read config in on_startup().

    Connection is lazy: the self.client property calls _get_connected_client()
    which connects on first use. on_startup() should only prepare state (read
    config values), not establish the connection.
    """

    def __init__(self) -> None:
        """Initialize the client."""
        super().__init__()
        self._client: Any = None

    async def _get_connected_client(self):
        """Get the client, connecting lazily if necessary."""
        if not self._is_connected():
            await self.connect()
        return self._client

    @property
    def client(self):
        """Get the client, ensuring connection if necessary.

        Returns a coroutine that performs reconnect if needed.
        """
        return self._get_connected_client()

    async def on_startup(self) -> None:
        """No-op. Clients connect lazily on first use via the client property."""

    async def on_shutdown(self) -> None:
        """Close the client connection."""
        await self.close()

    @abstractmethod
    def _is_connected(self) -> bool:
        """Check if the client is currently connected."""
        raise NotImplementedError

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the underlying service."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, topic: str, callback: Callable[[CloudEvent], Awaitable[None]]) -> None:
        """Subscribe to a topic with a callback for incoming events."""
        raise NotImplementedError

    @abstractmethod
    async def publish(self, topic: str, event: CloudEvent, routing_key: str | None = None) -> None:
        """Publish a CloudEvent to a topic."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> "ComponentHealth":
        """Check the health of the client."""
        raise NotImplementedError
