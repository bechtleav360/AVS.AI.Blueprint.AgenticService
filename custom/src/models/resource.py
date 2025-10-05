"""Typed invoice input model for the calculate_invoice tool."""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class InvoiceLineItem(BaseModel):
    """A single line item on an invoice."""

    description: str = Field(..., description="Description of the item or service")
    quantity: Decimal = Field(..., gt=0, description="Quantity of items")
    unit_price: Decimal = Field(..., ge=0, description="Price per unit")
    tax_rate: Decimal | None = Field(
        None, ge=0, le=1, description="Tax rate as decimal (e.g., 0.19 for 19%)"
    )


class InvoiceInput(BaseModel):
    """Invoice data used by the calculate_invoice tool.

    This model represents an invoice with line items, allowing the agent to
    compute totals and infer taxes.
    """

    invoice_id: str = Field(
        ...,
        description="Unique invoice identifier",
        examples=["INV-2025-001", "BILL-12345"],
    )
    line_items: list[InvoiceLineItem] = Field(
        ...,
        min_length=1,
        description="List of line items on the invoice",
    )
    currency: str = Field(
        default="EUR",
        description="Currency code (ISO 4217)",
        examples=["EUR", "USD", "GBP"],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (customer info, dates, etc.)",
    )
