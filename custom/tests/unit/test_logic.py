"""Unit tests for invoice processing domain logic."""

from decimal import Decimal

import pytest

from custom.src.services import InvoiceProcessingLogic


@pytest.fixture
def sample_invoice():
    return {
        "invoice_id": "INV-100",
        "line_items": [
            {"description": "Consulting", "quantity": "10", "unit_price": "150", "tax_rate": "0.19"},
            {"description": "Software", "quantity": "1", "unit_price": "500", "tax_rate": "0.07"},
        ],
        "currency": "EUR",
    }


def test_calculate_invoice_returns_expected_fields(sample_invoice):
    result = InvoiceProcessingLogic.calculate_invoice(sample_invoice)

    assert result["status"] == "valid"
    assert Decimal(str(result["total_amount"])) > 0
    assert "evidence" in result
    assert result["confidence"] >= 0.7


def test_calculate_invoice_handles_missing_items():
    result = InvoiceProcessingLogic.calculate_invoice({"line_items": []})

    assert result["status"] == "incomplete"
    assert Decimal(str(result["total_amount"])) == Decimal("0")
    assert "No line items provided" in result["evidence"]


def test_generate_recommendations_produces_guidance(sample_invoice):
    calculation = InvoiceProcessingLogic.calculate_invoice(sample_invoice)
    recommendations = InvoiceProcessingLogic.generate_recommendations(calculation, sample_invoice)

    assert isinstance(recommendations, list)
    assert all(isinstance(rec, str) for rec in recommendations)

