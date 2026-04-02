"""Unit tests for order event handlers."""

import pytest

from unittest.mock import MagicMock, AsyncMock

from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from src.handlers.order_validation_handler import OrderValidationHandler
from src.handlers.order_enrichment_handler import OrderEnrichmentHandler
from src.models.schemas import ValidationError as VError


def _make_event(data: dict, event_type: str = "order.created") -> GenericCloudEvent:
    return GenericCloudEvent(
        id="evt-test-001",
        type=event_type,
        source="/tests",
        data=data,
    )


VALID_ORDER_DATA = {
    "order_id": "order-100",
    "customer_id": "cust-1",
    "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": 25.0}],
    "shipping_address": "456 Test Ave",
    "total_amount": 25.0,
}

INVALID_ORDER_DATA = {
    "order_id": "order-101",
    "customer_id": "cust-2",
    "items": [],
    "shipping_address": "",
    "total_amount": -10.0,
}


# ---------------------------------------------------------------------------
# OrderValidationHandler
# ---------------------------------------------------------------------------


class TestOrderValidationHandler:
    @pytest.fixture
    def handler(self):
        h = object.__new__(OrderValidationHandler)
        h._priority = 10
        h._name = "order_validation_handler"

        mock_service = MagicMock()
        mock_service.validate_order.return_value = (True, [])
        mock_service.cache_order_status = MagicMock()
        h._order_service = mock_service
        return h

    @pytest.mark.asyncio
    async def test_can_handle_order_created(self, handler):
        event = _make_event(VALID_ORDER_DATA)
        assert await handler.can_handle_event(event, {}) is True

    @pytest.mark.asyncio
    async def test_ignores_other_events(self, handler):
        event = _make_event(VALID_ORDER_DATA, event_type="order.shipped")
        assert await handler.can_handle_event(event, {}) is False

    @pytest.mark.asyncio
    async def test_valid_order_returns_none(self, handler):
        handler._order_service.validate_order.return_value = (True, [])
        event = _make_event(VALID_ORDER_DATA)
        result = await handler.handle_event(event, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_order_returns_rejected(self, handler):
        errors = [
            VError(field="items", message="Order must contain at least one item"),
            VError(field="shipping_address", message="Shipping address is required"),
        ]
        handler._order_service.validate_order.return_value = (False, errors)
        event = _make_event(INVALID_ORDER_DATA)
        result = await handler.handle_event(event, {})

        assert isinstance(result, HandlerResult)
        assert result.event_type == "order.rejected"
        assert result.data["order_id"] == "order-101"
        assert len(result.data["errors"]) == 2

    @pytest.mark.asyncio
    async def test_rejection_caches_status(self, handler):
        errors = [VError(field="items", message="empty")]
        handler._order_service.validate_order.return_value = (False, errors)
        event = _make_event(INVALID_ORDER_DATA)
        await handler.handle_event(event, {})
        handler._order_service.cache_order_status.assert_called_once()

    def test_published_event_types(self, handler):
        assert handler.get_published_event_types() == (
            "order.validated",
            "order.rejected",
        )


# ---------------------------------------------------------------------------
# OrderEnrichmentHandler
# ---------------------------------------------------------------------------


class TestOrderEnrichmentHandler:
    @pytest.fixture
    def handler(self):
        h = object.__new__(OrderEnrichmentHandler)
        h._priority = 20
        h._name = "order_enrichment_handler"

        mock_service = MagicMock()
        mock_service.enrich_order.return_value = {
            "order_id": "order-100",
            "customer_id": "cust-1",
            "items": [{"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": 25.0}],
            "shipping_address": "456 Test Ave",
            "total_amount": 25.0,
            "tax_amount": 2.5,
            "grand_total": 27.5,
            "shipping_estimate": "3-5 business days",
            "processed_at": "2026-03-30T10:00:00+00:00",
        }
        mock_service.cache_order_status = MagicMock()
        h._order_service = mock_service
        return h

    @pytest.mark.asyncio
    async def test_can_handle_order_created(self, handler):
        event = _make_event(VALID_ORDER_DATA)
        assert await handler.can_handle_event(event, {}) is True

    @pytest.mark.asyncio
    async def test_returns_validated_result(self, handler):
        event = _make_event(VALID_ORDER_DATA)
        result = await handler.handle_event(event, {})

        assert isinstance(result, HandlerResult)
        assert result.event_type == "order.validated"
        assert result.data["order_id"] == "order-100"
        assert result.data["tax_amount"] == 2.5

    @pytest.mark.asyncio
    async def test_caches_validated_status(self, handler):
        event = _make_event(VALID_ORDER_DATA)
        await handler.handle_event(event, {})
        handler._order_service.cache_order_status.assert_called_once_with(
            "order-100",
            "validated",
            handler._order_service.enrich_order.return_value,
        )
