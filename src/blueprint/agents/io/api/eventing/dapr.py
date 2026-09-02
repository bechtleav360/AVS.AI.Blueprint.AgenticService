"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, status

from ....models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ....clients.io.dapr_client import DaprClient
from ....models import ProcessingStatus
from ....models.events import CloudEvent
from .event_handling_base import EventHandlingBase
from ..rest_api_base import RestApiBase

logger = logging.getLogger(__name__)


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

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self._client: DaprClient | None = None

    async def on_startup(self) -> None:
        self._client = self.registry.get_component(DaprClient)

        # Delivery is driven by the subscription document in subscribe(); this handing-over
        # exists so the client starts its sidecar-reachability retry and can report
        # subscriptions_ready. Removing it would silently disable readiness gating.
        topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {
            topic: self._make_event_callback(topic) for topic in self._declared_topics()
        }

        if topic_callbacks:
            await self._client.subscribe(topic_callbacks)
        else:
            logger.debug("DaprEventing: no handler declared a topic; nothing to report as ready")

    async def on_shutdown(self) -> None:
        pass

    def _make_event_callback(self, topic: str) -> Callable[[CloudEvent[Any]], Awaitable[None]]:
        """Return an async callback that routes an incoming Dapr event through the handler chain."""

        async def _process_event(event: CloudEvent[Any]) -> None:
            try:
                context = {"dapr_topic": topic}
                await self._process_cloud_event(event, context)
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
        """Return every topic declared by a registered handler, in declaration order."""
        topics: dict[str, None] = {}
        for handler in self.registry.get_event_handler():
            for topic in handler.get_subscribed_topics():
                if topic:
                    topics[topic] = None
        return list(topics)

    @RestApiBase.post("/events/{topic}", tags=["dapr"])
    async def publish(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        """Generic Dapr event handler that processes events through the unified service."""

        try:
            context = {
                "dapr_topic": topic,
            }

            processing_result = await self._process_cloud_event(cloud_event, context)

            if processing_result.status == ProcessingStatus.PROCESSED:
                return {"status": "SUCCESS"}

            logger.warning(
                "Processing service returned non-success status %s for topic %s",
                processing_result.status.value,
                topic,
            )
            failure_reason = processing_result.message or processing_result.status.value or "unknown_status"
            return {"status": "RETRY", "reason": failure_reason}

        except RetryableHandlerError as exc:
            logger.error("Retrying message for topic %s: %s", topic, str(exc), exc_info=True)
            return {"status": "RETRY", "reason": exc.reason}

        except InvalidEventError as exc:
            logger.error("Dropping message for topic %s: %s", topic, str(exc), exc_info=True)
            return {"status": "DROP", "reason": exc.reason}

        except CriticalHandlerError as exc:
            logger.error("Critical error for topic %s: %s", topic, str(exc), exc_info=True)
            return {"status": "RETRY", "reason": exc.reason}

        except Exception as exc:  # pragma: no cover - integration behaviour
            logger.error("Processing service failed for Dapr topic %s: %s", topic, str(exc), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Dapr event handling failed",
            ) from exc
