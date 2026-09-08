"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ....clients.io.dapr_client import DaprClient
from ....component.namespace import ROOT_LABEL, ROOT_NAMESPACE
from ....models.errors import DeliveryDisposition, HandlerError, disposition_for
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

    Config keys
    ~~~~~~~~~~~
    ``dapr_pubsub_name`` (str, default ``"pubsub"``): the Dapr pub/sub component to bind to.
    ``dapr_declarative_subscriptions`` (bool, default ``False``): set ``True`` when
    subscriptions are declared outside the application (CRD or YAML) so the discovery
    endpoint returns an empty document and the sidecar cannot subscribe twice.
    """

    route_class = DaprDeliveryRoute

    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        """Initialize the Dapr endpoint for one agent.

        Args:
            namespace: The agent this endpoint declares subscriptions for. ``""`` is the root,
                which is the whole of a single-agent application.
        """
        super().__init__(should_register=False, namespace=namespace)
        self._client: DaprClient | None = None

    async def on_startup(self) -> None:
        self._client = self.registry.get_component(DaprClient, namespace=self.namespace)

        # Delivery is driven by the subscription document in subscribe(); this handing-over
        # exists so the client starts its sidecar-reachability retry and can report
        # subscriptions_ready. Removing it would silently disable readiness gating.
        topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {
            topic: self._make_event_callback(topic) for topic in self._declared_topics()
        }

        if topic_callbacks:
            logger.info(
                "Namespace '%s' declares %d topic(s) to the sidecar: %s",
                self.namespace or ROOT_LABEL,
                len(topic_callbacks),
                ", ".join(topic_callbacks),
            )
            await self._client.subscribe(topic_callbacks)
        else:
            logger.debug(
                "DaprEventing: no handler in namespace '%s' declared a topic; nothing to report as ready",
                self.namespace or ROOT_LABEL,
            )

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
        return [{"pubsubname": pubsub_name, "topic": topic, "route": f"/events/{topic}"} for topic in self._declared_topics()]

    def _declared_topics(self) -> list[str]:
        """Return the topics this agent's handlers declare, in declaration order.

        Scoped to this agent's namespace for the reason ``HandlerChain._handlers`` names it
        too: on the root registry an omitted namespace means *every* namespace, so the root
        endpoint would publish every agent's topics into one subscription document and the
        sidecar would deliver them all through the root chain.
        """
        topics: dict[str, None] = {}
        for handler in self.registry.get_event_handler(namespace=self.namespace):
            for topic in handler.get_subscribed_topics():
                if topic:
                    topics[topic] = None
        return list(topics)

    @RestApiBase.post("/events/{topic}", tags=["dapr"])
    async def publish(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        """Receive an event from the sidecar and answer with its acknowledgement.

        The returned dict is the acknowledgement, so this method is Dapr's equivalent of
        ``NATSClient._settle`` and follows the same table (spec sec. 7.2): a handler chain
        that returned answers ``SUCCESS`` whatever its status, and a raised exception is
        classified by ``disposition_for`` and rendered into Dapr's words. One ``except``
        rather than one per error type, so the two transports cannot drift apart.
        """

        try:
            await self._process_cloud_event(cloud_event, {"dapr_topic": topic}, topic)
        except Exception as exc:
            disposition = disposition_for(exc)
            reason = exc.reason if isinstance(exc, HandlerError) else str(exc)
            logger.error(
                "Handler failed for event %s on topic '%s', answering %s: %s",
                cloud_event.id,
                topic,
                dapr_status(disposition),
                exc,
                exc_info=True,
            )
            return {"status": dapr_status(disposition), "reason": reason}

        # An unmatched event acknowledges like any other completed dispatch; the accounting
        # that keeps it visible lives in _process_cloud_event, shared with the NATS edge.
        return {"status": dapr_status(DeliveryDisposition.ACK)}
