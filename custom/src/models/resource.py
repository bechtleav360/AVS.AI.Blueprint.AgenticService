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

    NOTE: vLLM doesn't support $defs in JSON schemas, so we use a custom
    schema that inlines the line_items structure.
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

    @classmethod
    def model_json_schema(cls, **kwargs):
        """Generate vLLM-compatible JSON schema without $defs.

        This flattens the schema by inlining the InvoiceLineItem structure
        directly into the line_items array definition.
        """
        description = (
            "Invoice data used by the calculate_invoice tool.\n\n"
            "This model represents an invoice with line items, "
            "allowing the agent to\ncompute totals and infer taxes."
        )
        return {
            "type": "object",
            "description": description,
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "Unique invoice identifier",
                    "examples": ["INV-2025-001", "BILL-12345"],
                },
                "line_items": {
                    "type": "array",
                    "description": "List of line items on the invoice",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "Description of the item or service",
                            },
                            "quantity": {
                                "anyOf": [
                                    {"type": "number", "exclusiveMinimum": 0.0},
                                    {"type": "string"},
                                ],
                                "description": "Quantity of items",
                            },
                            "unit_price": {
                                "anyOf": [
                                    {"type": "number", "minimum": 0.0},
                                    {"type": "string"},
                                ],
                                "description": "Price per unit",
                            },
                            "tax_rate": {
                                "anyOf": [
                                    {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                    {"type": "string"},
                                    {"type": "null"},
                                ],
                                "default": None,
                                "description": "Tax rate as decimal (e.g., 0.19 for 19%)",
                            },
                        },
                        "required": ["description", "quantity", "unit_price"],
                    },
                },
                "currency": {
                    "type": "string",
                    "default": "EUR",
                    "description": "Currency code (ISO 4217)",
                    "examples": ["EUR", "USD", "GBP"],
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Additional metadata (customer info, dates, etc.)",
                },
            },
            "required": ["invoice_id", "line_items"],
        }
