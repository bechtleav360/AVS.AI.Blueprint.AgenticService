"""Async service tests for custom runtime-related utilities."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from custom.src.models.resource import InvoiceInput, InvoiceLineItem
from custom.src.services import HealthCheckService, InvoiceProcessingLogic


@pytest.mark.asyncio
async def test_health_check_service_returns_true():
    service = HealthCheckService()
    assert await service.check_health() is True


@pytest.mark.asyncio
async def test_calculate_invoice_tool_returns_analysis():
    invoice = InvoiceInput(
        invoice_id="INV-42",
        currency="EUR",
        line_items=[
            InvoiceLineItem(description="Consulting", quantity="5", unit_price="200", tax_rate="0.19"),
            InvoiceLineItem(description="Support", quantity="2", unit_price="150", tax_rate="0.07"),
        ],
    )

    ctx = SimpleNamespace(
        deps=SimpleNamespace(correlation_id=uuid4(), event_id=uuid4()),
    )

    result = await InvoiceProcessingLogic.calculate_invoice_tool(ctx, invoice)

    assert result.invoice_id == "INV-42"
    assert result.status in {"valid", "incomplete"}
    assert result.metadata["context"]["correlation_id"] is not None
