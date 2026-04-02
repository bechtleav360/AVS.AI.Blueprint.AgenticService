"""Handler that enriches validated orders (priority 20)."""

import logging
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..models.schemas import OrderPayload
from ..services.order_service import OrderService

logger = logging.getLogger(__name__)


class OrderEnrichmentHandler(EventHandlerBase):
    """Enriches valid orders with tax, shipping estimate, and timestamps.

    Runs after ``OrderValidationHandler`` (priority 20 > 10).  Only reached
    when validation passed (the validation handler returned ``None``).
    Publishes an ``order.validated`` event with the enriched data.
    """

    def __init__(self) -> None:
        super().__init__(priority=20)
        self._order_service: OrderService | None = None

    async def on_startup(self) -> None:
        self._order_service = self.registry.get_service(OrderService)
        logger.info("OrderEnrichmentHandler started")

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> bool:
        return event.type == "order.created"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult:
        assert self._order_service is not None
        payload = OrderPayload(**event.data)

        enriched = self._order_service.enrich_order(payload)
        logger.info("Order %s enriched successfully", payload.order_id)

        self._order_service.cache_order_status(
            payload.order_id,
            "validated",
            enriched,
        )

        return HandlerResult(
            event_type="order.validated",
            data=enriched,
        )

    def get_published_event_types(self) -> tuple[str, str]:
        return ("order.validated", "order.rejected")
