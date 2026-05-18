"""Handler that validates incoming order events (priority 10)."""

import logging
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..models.schemas import OrderPayload
from ..services.order_service import OrderService

logger = logging.getLogger(__name__)


class OrderValidationHandler(EventHandlerBase):
    """Validates order.created events.

    If the order is invalid, publishes an ``order.rejected`` event and
    short-circuits the handler chain.  If valid, returns ``None`` so the
    next handler in the chain (enrichment) can process the order.
    """

    def __init__(self) -> None:
        super().__init__(priority=10)
        self._order_service: OrderService | None = None

    async def on_startup(self) -> None:
        self._order_service = self.registry.get_service(OrderService)
        logger.info("OrderValidationHandler started")

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "order.created"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        assert self._order_service is not None
        payload = OrderPayload(**event.data)

        is_valid, errors = self._order_service.validate_order(payload)

        if not is_valid:
            error_dicts = [e.model_dump() for e in errors]
            logger.warning("Order %s rejected: %s", payload.order_id, error_dicts)
            self._order_service.cache_order_status(
                payload.order_id,
                "rejected",
                {"errors": error_dicts},
            )
            return HandlerResult(
                event_type="order.rejected",
                data={"order_id": payload.order_id, "errors": error_dicts},
            )

        logger.info("Order %s passed validation", payload.order_id)
        # Pass to the next handler in the chain
        return None

    def get_published_event_types(self) -> tuple[str, str]:
        return ("order.validated", "order.rejected")
