"""Base class for IO transport clients (Dapr, NATS, etc.)."""

from abc import ABC

from ..client_base import ClientBase


class IOClientBase(ClientBase, ABC):
    """Abstract base for IO transport clients.

    Extends ClientBase for message-bus and eventing transports (Dapr, NATS, etc.).
    Used by EventPublishingService and eventing endpoints to find the active
    transport client via the registry without matching AI clients.
    """


TOPIC_TRANSPORTS = ("dapr", "nats")
"""Values of ``event_bus`` that produce an :class:`IOClientBase`, and therefore carry topics.

``"sessions"`` is not one of them: it wires ``SessionsApiClient`` (a service) and
``SessionsBus``, which consumes SSE job notifications and never reads
``get_subscribed_topics()``. Anything that needs to publish to a topic or subscribe to one --
``EventPublishingService``, the eventing endpoints, an event-mode scheduler -- needs one of
these two.
"""
