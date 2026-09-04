"""Base class for event-driven REST API components."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from opentelemetry import metrics

from ....component.component import traced
from ....handler.handler_chain import DUPLICATE_CONTEXT_KEY
from ....models import ProcessingResult, ProcessingStatus
from ....models.errors import DeliveryDisposition
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .cloud_event_processor_mixin import CloudEventProcessorMixin
from .dapr_response import dapr_status

logger = logging.getLogger(__name__)

_UNHANDLED_EVENTS = metrics.get_meter(__name__).create_counter(
    name="blueprint.events.unhandled",
    description="Events a namespace received and found nothing to do with",
    unit="{event}",
)

_DUPLICATE_EVENTS = metrics.get_meter(__name__).create_counter(
    name="blueprint.events.duplicate",
    description="Events a namespace recognised as already processed and did not dispatch",
    unit="{event}",
)


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

    ROOT_NAMESPACE = ""
    """Namespace this component's events belong to.

    Components gain a real namespace in phase 2; until then every one of them lives in the
    root namespace, and this constant is the single place that assumption is written down.
    """

    @traced("topic", "cloud_event")
    async def handle_event(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        """Dispatch an event and return the acknowledgement dict Dapr reads.

        A handler chain that returned acknowledges whatever its status, per spec sec. 7.2:
        ``ProcessingStatus`` carries no failure value, so ``NO_HANDLER_FOUND`` means the
        dispatch completed and found nothing to do -- and no amount of redelivery makes a
        handler appear. Exceptions are not caught here; the transport edge classifies them.
        """
        await self._process_cloud_event(cloud_event, {"topic": topic}, topic)
        return {"status": dapr_status(DeliveryDisposition.ACK)}

    @abstractmethod
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Publish a CloudEvent to the broker (output path)."""
        raise NotImplementedError()

    async def _process_cloud_event(
        self,
        cloud_event: CloudEvent[Any],
        context: dict[str, Any],
        topic: str,
    ) -> ProcessingResult:
        """Dispatch a CloudEvent through the handler chain, letting failures propagate.

        Deliberately does not log those failures. Every caller of this method is a transport
        edge that must both decide the delivery disposition and report the failure (spec
        sec. 7.2), so logging here duplicated each error in the caller's output while adding
        nothing the edge does not already know -- and the edge knows the topic and the
        disposition, which this layer does not.

        A dispatch that matched no handler is counted, not reported. Deciding there is
        nothing to do is a handler's job and an ordinary outcome of it: an agent reads an
        event, finds no work in it, and says so. The count exists so an operator can see the
        *proportion* -- a namespace that declines nearly everything it receives is subscribed
        too broadly (spec sec. 7.7) -- and for no other reason. Nothing about it is an error,
        so it is not logged as one, and no per-topic state is kept: the topic arrives from a
        URL path under Dapr, and remembering each distinct value would let a caller grow this
        process's memory.

        A dispatch the chain skipped as a duplicate is counted apart from both (spec
        sec. 7.4). It reaches here looking exactly like an unmatched event -- no handler
        ran, so no result came back -- but the two say opposite things about the
        subscription: an unmatched event is one this namespace had no use for, while a
        duplicate is one it did use, once. Counting them together would make a redelivery
        storm read as a namespace subscribed too broadly.

        ``topic`` is passed separately from ``context`` because each transport spells its
        own key there (``nats_topic``, ``dapr_topic``), and those keys reach user handlers,
        so they cannot be unified without breaking them.
        """
        logger.debug("Processing CloudEvent: %s", cloud_event.id)
        processing_result = await self._dispatch_cloud_event(cloud_event, context)
        if context.get(DUPLICATE_CONTEXT_KEY):
            _DUPLICATE_EVENTS.add(1, {"namespace": self.ROOT_NAMESPACE, "topic": topic})
            logger.debug("Event %s on topic '%s' was already processed", cloud_event.id, topic)
        elif processing_result.status is ProcessingStatus.NO_HANDLER_FOUND:
            _UNHANDLED_EVENTS.add(1, {"namespace": self.ROOT_NAMESPACE, "topic": topic})
            logger.debug("No handler had work for event %s on topic '%s'", cloud_event.id, topic)
        return processing_result
