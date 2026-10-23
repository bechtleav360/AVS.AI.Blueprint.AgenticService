"""NATS eventing implementation using NATSClient."""

import logging
from typing import Any

from fastapi import HTTPException, status
from fastapi.routing import APIRoute

from ....clients.client_base import DeliveryCallback
from ....clients.io.nats_client import NATSClient
from ....clients.io.nats_connections import NATS_CONNECTION_CONTEXT_KEY, current_connection, current_delivery
from ....component.namespace import ROOT_NAMESPACE
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .event_handling_base import EventHandlingBase

logger = logging.getLogger(__name__)

NATS_SUBJECT_CONTEXT_KEY = "nats_subject"
"""Handler context key holding the subject a NATS message was delivered on.

Beside ``nats_topic``, which is the *subscription* -- possibly a wildcard such as ``t.*.risk.>`` --
this is the concrete subject that matched it, e.g. ``t.T1.risk.created``. It comes from the broker,
never from the event, so a handler can derive a tenant from it without trusting the publisher's
``tenantid``. Present only on events delivered by NATS.
"""


NATS_DELIVERY_ATTEMPT_CONTEXT_KEY = "nats_delivery_attempt"
"""Handler context key: which attempt this JetStream delivery is, 1-based (the broker's ``num_delivered``).

Present only on JetStream deliveries -- Core NATS does not redeliver. Read it with
``nats_max_deliver``: when the two are equal this is the last attempt, and a failure now is
dead-lettered or dropped rather than redelivered, so a handler can close or hand off what it
would otherwise leave open.
"""

NATS_MAX_DELIVER_CONTEXT_KEY = "nats_max_deliver"
"""Handler context key: the attempts the delivering consumer allows; ``None`` when unlimited or unknown.

Present exactly when ``nats_delivery_attempt`` is. On a named connection the value is the
binding's ``max_deliver``; on the agent's own consumers it is ``nats_max_deliver``.
"""


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

    In a group its publish endpoint is ``/api/<agent>/nats/events/{topic}``; standalone it
    stays ``/events/{topic}`` (spec sec. 11.2).
    """

    group_segment = "nats"

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

        topic_callbacks: dict[str, DeliveryCallback] = {topic: self._make_event_callback(topic) for topic in self._declared_topics()}

        if topic_callbacks:
            if self.namespace:
                logger.info(
                    "Namespace '%s' subscribes to %d topic(s): %s",
                    self.namespace,
                    len(topic_callbacks),
                    ", ".join(topic_callbacks),
                )
            else:
                for topic in topic_callbacks:
                    logger.info("NatsEventing: auto-subscribed to topic '%s'", topic)
            await self._client.subscribe(topic_callbacks)
        elif self.namespace:
            logger.info("NatsEventing: no auto-subscriptions configured for namespace '%s'", self.namespace)
        else:
            logger.info("NatsEventing: no auto-subscriptions configured")

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

    def _make_event_callback(self, topic: str) -> DeliveryCallback:
        """Return an async callback that routes an incoming event through the handler chain."""

        async def _process_event(event: CloudEvent[Any], subject: str) -> None:
            context: dict[str, Any] = {"nats_topic": topic, NATS_SUBJECT_CONTEXT_KEY: subject}
            connection = current_connection()
            if connection is not None:
                # Only a run from a named connection has one; the default connection adds no key (N6).
                context[NATS_CONNECTION_CONTEXT_KEY] = connection
            delivery = current_delivery()
            if delivery is not None:
                # JetStream only, on every connection: Core NATS has no redelivery to count.
                context[NATS_DELIVERY_ATTEMPT_CONTEXT_KEY] = delivery.attempt
                context[NATS_MAX_DELIVER_CONTEXT_KEY] = delivery.max_deliver
            processing_result = await self._process_cloud_event(event, context, topic)
            logger.debug(
                "Processed CloudEvent %s on topic %s with status %s",
                event.id,
                topic,
                processing_result.status.value,
            )

        return _process_event

    def drop_publish_route(self) -> None:
        """Remove ``POST /events/{topic}`` before mounting, for ``operator_routes_enabled = false`` (B1)."""
        self.router.routes[:] = [route for route in self.router.routes if not (isinstance(route, APIRoute) and route.name == "publish")]

    @RestApiBase.post("/events/{topic}", tags=["nats"])
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Publish a CloudEvent to a NATS topic.

        **A tenant's subject is refused** (B1): the route has no authentication of its own, and a
        subject a tenant connection owns would put the event into that tenant's stream, to run under
        the tenant's identity -- the reason plan D4 refuses handler results on such an agent. Turn
        the route off altogether with ``operator_routes_enabled = false``.

        Args:
            topic: The topic to publish to.
            event: The CloudEvent to publish.

        Returns:
            Success message.

        Raises:
            HTTPException: 403 for a subject one of this agent's tenants owns.
        """
        if not self._client:
            raise RuntimeError("NATS client not initialized")
        owned = self._client.tenant_subject(topic)
        if owned is not None:
            logger.warning("Refused to publish event %s through the HTTP route: %s", event.id, owned)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{owned}. An event published here would run under that tenant's identity; it is refused.",
            )

        await self._client.publish(topic, event)
        return {"message": f"Published event {event.id} to topic {topic}"}
