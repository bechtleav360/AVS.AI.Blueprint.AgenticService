"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ....clients.io.dapr_client import DaprClient
from ....component.namespace import ROOT_LABEL, ROOT_NAMESPACE, namespace_of
from ....models.errors import DeliveryDisposition, HandlerError, combined_disposition, disposition_for
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .dapr_response import dapr_status
from .event_handling_base import EventHandlingBase

logger = logging.getLogger(__name__)


class DaprDeliveryRoute(APIRoute):
    """Answer an unparseable delivery with ``DROP`` instead of letting FastAPI answer 422.

    Under NATS the framework decodes the payload itself, so a body that cannot become a
    CloudEvent is terminated by ``NATSClient._settle`` -- it will not parse on redelivery
    either. Under Dapr the body is parsed by FastAPI before any framework code runs, so
    that same payload produced a 422 the sidecar reads as a failed call and retries to
    ``max_deliver``: the one row of the spec sec. 7.2 table where the two transports
    disagreed for a structural reason rather than a coding one.

    Wrapping the route handler is what makes the answer route-scoped. An application-wide
    ``RequestValidationError`` handler would also answer for ordinary REST endpoints, where
    422 is the correct reply and ``{"status": "DROP"}`` would be nonsense.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def drop_unparseable_delivery(request: Request) -> Response:
            try:
                return await handle(request)
            except RequestValidationError as exc:
                logger.error("Discarding unparseable delivery on '%s': %s", request.url.path, exc)
                return JSONResponse({"status": dapr_status(DeliveryDisposition.TERM), "reason": "payload is not a CloudEvent"})

        return drop_unparseable_delivery


class DaprEventing(EventHandlingBase):
    """Implements event handling using Dapr pub/sub.

    The application holds no broker connection -- the sidecar does. The sidecar discovers
    what to deliver by calling ``GET /dapr/subscribe``, then pushes each message to
    ``POST /events/{topic}``, whose response body is the acknowledgement.

    Both halves are driven by the same ``get_subscribed_topics()`` declarations the NATS
    transport uses:

    - ``subscribe()`` renders them as the sidecar's subscription document, which is what
      actually causes delivery.
    - ``on_startup`` also hands them to ``DaprClient``, which uses them only to start the
      sidecar-reachability retry and to report ``subscriptions_ready`` through
      ``health_check()``. The client never invokes those callbacks, because delivery arrives
      over HTTP rather than through a client-side subscription.

    One endpoint for the process, fanned out to the agents
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Unlike the NATS endpoint, there is exactly **one** of these however many agents the process
    hosts, and it lives at the root. The two paths above are fixed by Dapr's protocol: the
    sidecar fetches the document from one place and posts deliveries where the document says.
    An endpoint per agent, each behind its own prefix, would leave the sidecar with no document
    to fetch at all.

    So the routing that NATS gets from the broker -- one consumer per ``(namespace, topic)`` --
    is done here instead, in the process:

    - :meth:`subscribe` returns the **union** of every agent's declared topics, deduplicated,
      because the sidecar needs telling once per topic.
    - :meth:`publish` looks the delivered topic up in :meth:`_agents_for` and dispatches once
      **per agent that declared it**, each through that agent's own handler chain. Two agents
      declaring one topic therefore both receive it, which is the same rule spec sec. 7.6 states
      for the broker-side case.
    - The one acknowledgement the sidecar reads is the combination of what each dispatch earned
      (:func:`combined_disposition`).

    **The cost, which has no equivalent under NATS: a redelivery is shared.** There is one
    delivery, so there is one acknowledgement; if any agent asks for a retry, every agent in the
    group sees the message again. A grouped Dapr deployment therefore wants
    ``idempotency_enabled`` set, or handlers that tolerate a repeat. Under NATS each agent has
    its own consumer and its own acknowledgement, and no such coupling exists.

    Config keys
    ~~~~~~~~~~~
    ``dapr_pubsub_name`` (str, default ``"pubsub"``): the Dapr pub/sub component to bind to.
    ``dapr_declarative_subscriptions`` (bool, default ``False``): set ``True`` when
    subscriptions are declared outside the application (CRD or YAML) so the discovery
    endpoint returns an empty document and the sidecar cannot subscribe twice. Note that the
    framework then has no topic-to-agent map, so a delivery is offered to every agent -- see
    :meth:`_agents_for`.
    """

    route_class = DaprDeliveryRoute

    def __init__(self) -> None:
        """Initialize the process's Dapr endpoint.

        **Takes no namespace, unlike every other transport component.** There is one of these
        per process and it belongs to the root, because Dapr's two paths are fixed by its
        protocol and cannot be prefixed per agent. Making that structural rather than
        documented is what keeps :meth:`_topics_by_agent` correct: it reads *every* handler in
        the process, which it can only do because ``self.registry`` is the application's
        registry rather than one agent's view of it. A namespaced instance would see one
        agent's handlers and silently route only that agent's topics.
        """
        super().__init__(should_register=False)
        # The client per agent, not one client: this endpoint is shared by the process, and
        # the clients are not. Populated in on_startup; empty when no agent declared a topic.
        self._clients: dict[str, DaprClient] = {}

    async def on_startup(self) -> None:
        """Hand each agent's topics to that agent's client, for readiness reporting.

        Delivery is driven by the subscription document in :meth:`subscribe`; this handing-over
        exists so each client starts its sidecar-reachability retry and can report
        ``subscriptions_ready``. Removing it would silently disable readiness gating.

        Per agent rather than once for the process, even though this endpoint is shared: the
        client is per agent (spec sec. 6), and readiness reported against the wrong agent is
        what makes ``readiness_policy = "critical"`` unusable.
        """
        topics_by_agent = self._topics_by_agent()
        if not topics_by_agent:
            logger.debug("DaprEventing: no handler declared a topic; nothing to report as ready")
            return

        for namespace, topics in topics_by_agent.items():
            client = self.registry.get_component(DaprClient, namespace=namespace)
            self._clients[namespace] = client
            topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {
                topic: self._make_event_callback(topic) for topic in topics
            }
            logger.info(
                "Namespace '%s' declares %d topic(s) to the sidecar: %s",
                namespace or ROOT_LABEL,
                len(topic_callbacks),
                ", ".join(topic_callbacks),
            )
            await client.subscribe(topic_callbacks)

    async def on_shutdown(self) -> None:
        pass

    def _make_event_callback(self, topic: str) -> Callable[[CloudEvent[Any]], Awaitable[None]]:
        """Return an async callback that routes an incoming Dapr event through the handler chain."""

        async def _process_event(event: CloudEvent[Any]) -> None:
            try:
                context = {"dapr_topic": topic}
                await self._process_cloud_event(event, context, topic)
            except Exception as exc:
                logger.error("Event processing failed on topic %s: %s", topic, str(exc), exc_info=True)

        return _process_event

    @RestApiBase.get("/dapr/subscribe", tags=["dapr"])
    async def subscribe(self) -> list[dict[str, Any]]:
        """Return the subscription document the Dapr sidecar fetches at startup.

        One entry per topic declared by a registered handler, routed to this service's
        ``POST /events/{topic}`` endpoint. The sidecar calls this with no parameters, so the
        signature takes none: a required query parameter here answers 422 and the service
        receives nothing.

        Returns an empty document when ``dapr_declarative_subscriptions`` is set, so a
        deployment that declares its subscriptions as Kubernetes resources does not end up
        subscribed twice.

        Overriding this in user code is supported, but the override must re-apply
        ``@RestApiBase.get("/dapr/subscribe")`` -- route discovery walks the MRO subclass-first
        and an undecorated override claims the name without registering a route.
        """
        if self.config.get("dapr_declarative_subscriptions", False):
            logger.debug("DaprEventing: subscriptions are declared externally, returning an empty document")
            return []

        pubsub_name = self.config.get("dapr_pubsub_name", "pubsub")
        # route_prefix, not a bare '/events/...': this document is what makes the sidecar post
        # anywhere at all, so it has to name the path the router is actually mounted at. This
        # endpoint is always the root one, so the prefix is empty and the document is
        # byte-identical to what it always was -- the property is read rather than hardcoded so
        # the two cannot drift if that ever changes.
        return [
            {"pubsubname": pubsub_name, "topic": topic, "route": f"{self.route_prefix}/events/{topic}"} for topic in self._declared_topics()
        ]

    def _topics_by_agent(self) -> dict[str, list[str]]:
        """Return each agent's declared topics, keyed by namespace, in declaration order.

        Read from the handlers themselves rather than from any list of agents: an agent that
        declared no topic has nothing to subscribe and nothing to be delivered, so it does not
        appear here at all. Every handler in the process is walked, which is what makes this the
        one place that sees the whole routing picture -- and it is only safe because this
        endpoint is the process's single Dapr endpoint rather than one of several.
        """
        by_agent: dict[str, dict[str, None]] = {}
        # No namespace argument, which here means every namespace: this endpoint is the root
        # one -- enforced by __init__ taking no namespace at all -- so its registry is the
        # application's rather than one agent's view, and an omitted namespace is the whole
        # process. That is the one place in the framework where this reading is what is wanted.
        for handler in self.registry.get_event_handler():
            for topic in handler.get_subscribed_topics():
                if topic:
                    by_agent.setdefault(namespace_of(handler), {})[topic] = None
        return {namespace: list(topics) for namespace, topics in by_agent.items()}

    def _declared_topics(self) -> list[str]:
        """Return every topic any agent in this process declares, deduplicated.

        This is the union, not one agent's list, because it renders the sidecar's subscription
        document and the sidecar needs telling **once** per topic -- it delivers a topic to the
        application once however many agents want it. Fanning that one delivery out is
        :meth:`publish`'s job, not the sidecar's.
        """
        topics: dict[str, None] = {}
        for declared in self._topics_by_agent().values():
            for topic in declared:
                topics[topic] = None
        return list(topics)

    def _agents_for(self, topic: str) -> tuple[str, ...]:
        """Return the agents a delivery on ``topic`` is offered to.

        The agents that declared the topic, in a stable order. When **nobody** declared it,
        every agent that has handlers at all -- which is the same rule
        ``DispatchIndex.candidates`` applies one level down: a declaration narrows who is asked,
        and its absence cannot narrow anything to nothing.

        That fallback is what a topic arriving from outside the application needs.
        ``dapr_declarative_subscriptions`` makes the subscription document empty, so the
        framework never sees the topic list at all and no handler need declare anything; the
        sidecar still delivers. Sending such a delivery nowhere would silence the application,
        and an unhandled event acknowledges (spec sec. 7.2), so the events would be consumed and
        discarded. For a single-agent application both branches are the root, so this changes
        nothing there.
        """
        by_agent = self._topics_by_agent()
        declared = tuple(namespace for namespace, topics in by_agent.items() if topic in topics)
        if declared:
            return declared
        with_handlers = tuple(dict.fromkeys(namespace_of(handler) for handler in self.registry.get_event_handler()))
        return with_handlers or (ROOT_NAMESPACE,)

    def _is_paused(self, namespace: str) -> bool:
        """Whether ``namespace`` has been taken off its topics because it is degraded (C4).

        Read from that agent's own client rather than from any process-wide register of
        degraded agents: the client is the per-agent object the supervisor pauses, and asking
        it keeps the two transports answering the same question from the same state. An agent
        with no client cannot be paused, and is not.
        """
        return any(client.consumption_paused for client in self.registry.get_io_clients(namespace=namespace))

    @RestApiBase.post("/events/{topic}", tags=["dapr"])
    async def publish(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        """Receive an event from the sidecar, offer it to every agent that wants it, and answer.

        The returned dict is the acknowledgement, so this method is Dapr's equivalent of
        ``NATSClient._settle`` and follows the same table (spec sec. 7.2): a handler chain
        that returned acknowledges whatever its status, and a raised exception is classified by
        ``disposition_for`` and rendered into Dapr's words. One ``except`` rather than one per
        error type, so the two transports cannot drift apart.

        **One delivery, one answer, several agents.** Each agent named by :meth:`_agents_for`
        gets its own dispatch through its own chain, and a failure in one does not stop the
        others -- an agent that raised must not silently cancel a neighbour's work, which is
        what letting the exception out of the loop would do. The answers are then combined by
        :func:`combined_disposition`, whose docstring carries the ordering and its cost: a retry
        asked for by one agent redelivers to all of them.

        The reason string reports the first failure. There is one field for it and no way to
        return several, so it names the first agent that failed rather than concatenating; the
        per-agent errors are logged individually above it, each with its agent.
        """
        agents = self._agents_for(topic)
        dispositions: list[DeliveryDisposition] = []
        reason: str | None = None

        for namespace in agents:
            if self._is_paused(namespace):
                # C4 under a push transport. NATS stops consuming by draining its
                # subscriptions; the sidecar has no such notion -- it posts here whatever the
                # application thinks -- so the equivalent is to nak without dispatching,
                # which Dapr renders as RETRY and which redelivers the event to a replica
                # whose agent is up.
                dispositions.append(DeliveryDisposition.NAK)
                if reason is None:
                    reason = f"agent '{namespace or ROOT_LABEL}' is degraded and is not consuming"
                logger.warning(
                    "Event %s on topic '%s' was not offered to agent '%s': it is degraded and paused",
                    cloud_event.id,
                    topic,
                    namespace or ROOT_LABEL,
                )
                continue
            try:
                await self._process_cloud_event(cloud_event, {"dapr_topic": topic}, topic, namespace=namespace)
                dispositions.append(DeliveryDisposition.ACK)
            except Exception as exc:
                disposition = disposition_for(exc)
                dispositions.append(disposition)
                if reason is None:
                    reason = exc.reason if isinstance(exc, HandlerError) else str(exc)
                logger.error(
                    "Handler in namespace '%s' failed for event %s on topic '%s', answering %s: %s",
                    namespace or ROOT_LABEL,
                    cloud_event.id,
                    topic,
                    dapr_status(disposition),
                    exc,
                    exc_info=True,
                )

        combined = combined_disposition(dispositions)
        if len(agents) > 1:
            logger.debug(
                "Event %s on topic '%s' was offered to %d agents (%s); answering %s",
                cloud_event.id,
                topic,
                len(agents),
                ", ".join(namespace or ROOT_LABEL for namespace in agents),
                dapr_status(combined),
            )
        # An unmatched event acknowledges like any other completed dispatch; the accounting
        # that keeps it visible lives in _process_cloud_event, shared with the NATS edge.
        if reason is None:
            return {"status": dapr_status(combined)}
        return {"status": dapr_status(combined), "reason": reason}
