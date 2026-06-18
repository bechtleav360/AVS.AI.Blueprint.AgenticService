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

    Dapr subscriptions are declarative: the sidecar discovers topics via
    ``GET /dapr/subscribe`` and pushes events to ``POST /events/{topic}``.

    ``on_startup`` stores the topic→callback mapping in ``DaprClient`` and
    starts a background retry task that pings the sidecar until it responds.
    The client tracks ``subscriptions_ready`` and exposes it via
    ``health_check()`` so the readiness probe reflects sidecar availability.
    """

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self._client: DaprClient | None = None

    async def on_startup(self) -> None:
        self._client = self.registry.get_component(DaprClient)

        topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {}
        for handler in self.registry.get_event_handler():
            for topic in handler.get_subscribed_topics():
                if topic and topic not in topic_callbacks:
                    topic_callbacks[topic] = self._make_event_callback(topic)

        if topic_callbacks:
            await self._client.subscribe(topic_callbacks)
        else:
            logger.info("DaprEventing: no subscriptions configured")

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
    async def subscribe(self, topic: str, queue_group: str | None = None) -> dict[str, Any]:
        """Dapr subscription discovery endpoint.

        The Dapr sidecar calls this at startup to learn which topics to route
        to this service.  Override in user code to declare real subscriptions.

        Note: subscriptions can also be defined via Kubernetes resources.
        """
        return {}

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
