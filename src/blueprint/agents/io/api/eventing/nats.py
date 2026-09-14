"""NATS eventing implementation using NATSClient."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ....clients.io.nats_client import NATSClient
from ....component.namespace import ROOT_LABEL, ROOT_NAMESPACE
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .event_handling_base import EventHandlingBase

logger = logging.getLogger(__name__)


class NatsEventing(EventHandlingBase):
    """Implements event handling using NATS via NATSClient.

    ``on_startup`` collects the full topic→callback mapping from all registered
    handlers and config, then hands it to ``NATSClient.subscribe()``.  The client
    owns connection, retry, reconnect, and subscription-readiness tracking.

    The callback lets every exception through. A handler failure is the only way a
    failure reaches the transport -- ``ProcessingStatus`` has no failure value -- and
    the transport edge is what turns it into a nak or a term (spec sec. 7.2). Catching
    one here would acknowledge the event as successfully processed.

    One endpoint per agent
    ~~~~~~~~~~~~~~~~~~~~~~
    This component belongs to a namespace and subscribes on behalf of that agent alone: it
    reads that agent's handlers, that agent's ``nats_subscriptions``, and that agent's
    ``NATSClient``. A process hosting three agents therefore holds three of these, and each
    ``(namespace, topic)`` pair ends up with its own subscription and its own consumer, which
    is what spec sec. 7.6 requires.

    **Topic deduplication is per agent, and only per agent.** Two agents subscribing to the
    same topic both want the event, so there is no cross-agent "first declaration wins" --
    which would silently disable one agent's subscription, and could not be observed by its
    author running it alone. Deduplication happens inside one of these components, so it
    cannot reach across namespaces by construction.
    """

    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        """Initialize the NATS endpoint for one agent.

        Args:
            namespace: The agent this endpoint subscribes for. ``""`` is the root, which is
                the whole of a single-agent application.
        """
        super().__init__(should_register=False, namespace=namespace)
        self._client: NATSClient | None = None

    async def on_startup(self) -> None:
        """Subscribe this agent's topics through this agent's client."""
        self._client = self.registry.get_component(NATSClient, namespace=self.namespace)

        topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {
            topic: self._make_event_callback(topic) for topic in self._declared_topics()
        }

        if topic_callbacks:
            logger.info(
                "Namespace '%s' subscribes to %d topic(s): %s",
                self.namespace or ROOT_LABEL,
                len(topic_callbacks),
                ", ".join(topic_callbacks),
            )
            await self._client.subscribe(topic_callbacks)
        else:
            logger.info("NatsEventing: no auto-subscriptions configured for namespace '%s'", self.namespace or ROOT_LABEL)

    def _declared_topics(self) -> list[str]:
        """Return the topics this agent subscribes to, in declaration order.

        Two sources, in this order: the ``get_subscribed_topics()`` of this agent's handlers,
        then the ``nats_subscriptions`` config list. Both are scoped to this agent without
        anything here saying so -- ``self.registry`` and ``self.config`` are already this
        namespace's views, so the config key resolves ``<agent>.nats_subscriptions`` before
        falling back to the shared list (C5), and the handler query is filtered below.

        The namespace is named explicitly in the handler query for the reason it is named in
        ``HandlerChain._handlers``: on the root registry an omitted namespace means *every*
        namespace, so the root endpoint would otherwise subscribe to every agent's topics and
        deliver them all through the root chain.
        """
        topics: dict[str, None] = {}
        for handler in self.registry.get_event_handler(namespace=self.namespace):
            for topic in handler.get_subscribed_topics():
                if topic:
                    topics[topic] = None
        for topic in self.config.get_nats_subscription_config():
            if topic:
                topics[topic] = None
        return list(topics)

    async def on_shutdown(self) -> None:
        pass

    def _make_event_callback(self, topic: str) -> Callable[[CloudEvent[Any]], Awaitable[None]]:
        """Return an async callback that routes an incoming event through the handler chain."""

        async def _process_event(event: CloudEvent[Any]) -> None:
            context = {"nats_topic": topic}
            processing_result = await self._process_cloud_event(event, context, topic)
            logger.debug(
                "Processed CloudEvent %s on topic %s with status %s",
                event.id,
                topic,
                processing_result.status.value,
            )

        return _process_event

    @RestApiBase.post("/events/{topic}", tags=["nats"])
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Publish a CloudEvent to a NATS topic.

        Args:
            topic: The topic to publish to.
            event: The CloudEvent to publish.

        Returns:
            Success message.
        """
        if not self._client:
            raise RuntimeError("NATS client not initialized")

        await self._client.publish(topic, event)
        return {"message": f"Published event {event.id} to topic {topic}"}
