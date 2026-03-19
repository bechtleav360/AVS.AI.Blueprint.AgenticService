"""Base class for IO transport clients (Dapr, NATS, etc.)."""

from abc import ABC

from ..client_base import ClientBase


class IOClientBase(ClientBase, ABC):
    """Abstract base for IO transport clients.

    Extends ClientBase for message-bus and eventing transports (Dapr, NATS, etc.).
    Used by EventPublishingService and eventing endpoints to find the active
    transport client via the registry without matching AI clients.
    """
