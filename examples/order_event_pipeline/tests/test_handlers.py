"""Unit tests for OrderHandler: it translates, OrderService.process_order decides."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.models.events import GenericCloudEvent

from src.handlers.order_handler import OrderHandler
from src.models.domain_models import Order, OrderOutcome


def _make_event(data: dict, event_type: str = "order.created") -> GenericCloudEvent:
    return GenericCloudEvent(id="evt-test-001", type=event_type, source="/tests", data=data)


VALID_ORDER_DATA = {
    "order_id": "order-100",
    "customer_id": "cust-1",
    "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": 25.0}],
    "shipping_address": "456 Test Ave",
    "total_amount": 25.0,
}


@pytest.fixture
def handler():
    """An OrderHandler holding an OrderService double, as ``on_startup`` would leave it."""
    h = object.__new__(OrderHandler)
    h._priority = 10
    h._order_service = MagicMock()
    h._order_service.process_order = AsyncMock(return_value=OrderOutcome(status="validated", data={"order_id": "order-100"}))
    return h


class TestRouting:
    async def test_declares_and_accepts_order_created(self, handler):
        assert handler.get_handled_event_types() == ["order.created"]
        assert await handler.can_handle_event(_make_event(VALID_ORDER_DATA), {}) is True

    async def test_declines_other_events_without_calling_the_service(self, handler):
        assert await handler.can_handle_event(_make_event({}, event_type="order.shipped"), {}) is False
        handler._order_service.process_order.assert_not_awaited()


class TestTranslation:
    async def test_the_payload_reaches_the_service_as_a_domain_order(self, handler):
        await handler.handle_event(_make_event(VALID_ORDER_DATA), {})
        order = handler._order_service.process_order.await_args.args[0]
        assert isinstance(order, Order)
        assert order.order_id == "order-100"
        assert order.items[0].product_id == "p1"

    async def test_one_service_call_per_event(self, handler):
        await handler.handle_event(_make_event(VALID_ORDER_DATA), {})
        assert handler._order_service.process_order.await_count == 1
        assert [c for c in handler._order_service.method_calls if not c[0].startswith("process_order")] == []

    async def test_validated_is_published_as_order_validated(self, handler):
        result = await handler.handle_event(_make_event(VALID_ORDER_DATA), {})
        assert result.event_type == "order.validated"
        assert result.data == {"order_id": "order-100"}

    async def test_rejected_is_published_as_order_rejected(self, handler):
        handler._order_service.process_order.return_value = OrderOutcome(status="rejected", data={"order_id": "order-101", "errors": []})
        result = await handler.handle_event(_make_event(VALID_ORDER_DATA), {})
        assert result.event_type == "order.rejected"

    def test_published_event_types(self, handler):
        assert handler.get_published_event_types() == ("order.validated", "order.rejected")
