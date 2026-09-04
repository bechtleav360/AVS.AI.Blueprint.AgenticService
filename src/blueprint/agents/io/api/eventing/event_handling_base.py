"""Base class for event-driven REST API components."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from ....component.component import traced
from ....models import ProcessingResult, ProcessingStatus
from ....models.errors import DeliveryDisposition
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .cloud_event_processor_mixin import CloudEventProcessorMixin
from .dapr_response import dapr_status

logger = logging.getLogger(__name__)


class EventHandlingBase(RestApiBase, CloudEventProcessorMixin, ABC):
    """Base class for event-driven REST API components.

    Combines REST API routing (RestApiBase) with CloudEvent processing
    (CloudEventProcessorMixin) and adds structured error-handling and logging
    around the dispatch pipeline.

    Transport connection, topic subscriptions, and retry logic live entirely
    in the transport client (NATSClient, DaprClient). Subclasses implement
    ``on_startup`` to wire the client's managed subscription flow and declare
    their own REST endpoints via concrete ``publish`` implementations.
    """

    @traced("topic", "cloud_event")
    async def handle_event(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        """Dispatch an event and return the acknowledgement dict Dapr reads.

        A handler chain that returned acknowledges whatever its status, per spec sec. 7.2:
        ``ProcessingStatus`` carries no failure value, so ``NO_HANDLER_FOUND`` means the
        dispatch completed and found nothing to do -- and no amount of redelivery makes a
        handler appear. Exceptions are not caught here; the transport edge classifies them.
        """
        processing_result = await self._process_cloud_event(cloud_event, {"topic": topic})
        if processing_result.status != ProcessingStatus.PROCESSED:
            logger.warning("No handler matched event %s on topic '%s'; acknowledging it anyway", cloud_event.id, topic)
        return {"status": dapr_status(DeliveryDisposition.ACK)}

    @abstractmethod
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Publish a CloudEvent to the broker (output path)."""
        raise NotImplementedError()

    async def _process_cloud_event(
        self,
        cloud_event: CloudEvent[Any],
        context: dict[str, Any],
    ) -> ProcessingResult:
        """Dispatch a CloudEvent through the handler chain, letting failures propagate.

        Deliberately does not log them. Every caller of this method is a transport edge
        that must both decide the delivery disposition and report the failure (spec
        sec. 7.2), so logging here duplicated each error in the caller's output while
        adding nothing the edge does not already know -- and the edge knows the topic and
        the disposition, which this layer does not.
        """
        logger.debug("Processing CloudEvent: %s", cloud_event.id)
        return await self._dispatch_cloud_event(cloud_event, context)
