"""Unit tests for OrderService validation and enrichment logic."""

import pytest

from unittest.mock import MagicMock

from src.models.domain_models import Order, OrderLine
from src.services.order_service import OrderService


@pytest.fixture
def service():
    """Create an OrderService without triggering the Component registry.

    We instantiate with should_register=False by-passing the base __init__,
    then manually set the attributes the tests need.
    """
    svc = object.__new__(OrderService)
    svc._cache = None
    return svc


def _make_payload(**overrides) -> Order:
    defaults = {
        "order_id": "order-001",
        "customer_id": "cust-001",
        "items": [OrderLine(product_id="p1", name="Widget", quantity=1, unit_price=10.0)],
        "shipping_address": "123 Test St",
        "total_amount": 10.0,
    }
    defaults.update(overrides)
    return Order(**defaults)


class TestValidateOrder:
    def test_valid_order(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload())
        assert is_valid is True
        assert errors == []

    def test_empty_items(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload(items=[]))
        assert is_valid is False
        assert any(e.field == "items" for e in errors)

    def test_zero_total(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload(total_amount=0))
        assert is_valid is False
        assert any(e.field == "total_amount" for e in errors)

    def test_negative_total(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload(total_amount=-5.0))
        assert is_valid is False
        assert any(e.field == "total_amount" for e in errors)

    def test_empty_shipping_address(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload(shipping_address=""))
        assert is_valid is False
        assert any(e.field == "shipping_address" for e in errors)

    def test_whitespace_shipping_address(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload(shipping_address="   "))
        assert is_valid is False
        assert any(e.field == "shipping_address" for e in errors)

    def test_multiple_errors(self, service: OrderService):
        is_valid, errors = service.validate_order(_make_payload(items=[], total_amount=-1, shipping_address=""))
        assert is_valid is False
        assert len(errors) == 3


class TestEnrichOrder:
    def test_enrichment_adds_tax(self, service: OrderService):
        payload = _make_payload(total_amount=100.0)
        result = service.enrich_order(payload)
        assert result["tax_amount"] == 10.0
        assert result["grand_total"] == 110.0

    def test_enrichment_adds_shipping_estimate(self, service: OrderService):
        payload = _make_payload()
        result = service.enrich_order(payload)
        assert "shipping_estimate" in result

    def test_small_order_fast_shipping(self, service: OrderService):
        items = [OrderLine(product_id="p1", name="Widget", quantity=2, unit_price=5.0)]
        payload = _make_payload(items=items, total_amount=10.0)
        result = service.enrich_order(payload)
        assert result["shipping_estimate"] == "3-5 business days"

    def test_large_order_slow_shipping(self, service: OrderService):
        items = [OrderLine(product_id="p1", name="Widget", quantity=10, unit_price=5.0)]
        payload = _make_payload(items=items, total_amount=50.0)
        result = service.enrich_order(payload)
        assert result["shipping_estimate"] == "5-7 business days"

    def test_enrichment_has_processed_at(self, service: OrderService):
        payload = _make_payload()
        result = service.enrich_order(payload)
        assert "processed_at" in result


class TestProcessOrder:
    """The facade the handler calls: validate, then enrich, and cache the status either way."""

    async def test_a_valid_order_is_validated_enriched_and_cached(self, service: OrderService):
        service._cache = MagicMock()
        outcome = await service.process_order(_make_payload())
        assert outcome.status == "validated"
        assert outcome.data["tax_amount"] == 1.0
        assert service._cache.set.call_args.args[1]["status"] == "validated"

    async def test_an_invalid_order_is_rejected_with_its_errors_and_cached(self, service: OrderService):
        service._cache = MagicMock()
        outcome = await service.process_order(_make_payload(items=[], total_amount=0))
        assert outcome.status == "rejected"
        assert {e["field"] for e in outcome.data["errors"]} == {"items", "total_amount"}
        assert service._cache.set.call_args.args[1]["status"] == "rejected"
