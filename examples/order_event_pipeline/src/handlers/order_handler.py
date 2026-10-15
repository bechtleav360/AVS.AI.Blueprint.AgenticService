"""The handler for ``order.created``: translate the event, call the service once, translate back."""

import logging
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..models.domain import Order
from ..models.schemas import OrderPayload
from ..services.order_service import OrderService

logger = logging.getLogger(__name__)

ORDER_CREATED = "order.created"
_EVENT_TYPE_BY_STATUS = {"validated": "order.validated", "rejected": "order.rejected"}


class OrderHandler(EventHandlerBase):
    """Processes order.created. Validation and enrichment are OrderService.process_order's decisions."""

    def __init__(self) -> None:
        super().__init__(priority=10)

    async def on_startup(self) -> None:
        self._order_service = self.registry.get_service(OrderService)

    async def on_shutdown(self) -> None:
        pass

    def get_handled_event_types(self) -> list[str]:
        return [ORDER_CREATED]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == ORDER_CREATED

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
        payload = self.extract_payload(event, OrderPayload)
        outcome = await self._order_service.process_order(Order.model_validate(payload.model_dump()))
        return HandlerResult(event_type=_EVENT_TYPE_BY_STATUS[outcome.status], data=outcome.data)

    def get_published_event_types(self) -> tuple[str, str]:
        return ("order.validated", "order.rejected")
