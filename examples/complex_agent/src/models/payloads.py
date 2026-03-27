"""Data Transfer Objects (DTOs) for REST API endpoints."""

from pydantic import BaseModel, ConfigDict, Field


class CustomPayload(BaseModel):
    """Define the expected payload for invoice processing endpoint.

    Accepts unstructured text (e.g., from OCR) that the agent will parse and analyze.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "invoice_text": """
                        Invoice #INV-2025-001
                        Date: 2025-01-15
                        Customer: Bechtle AG

                        Line Items:
                        1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr
                        2. Software license - Qty: 1 @ 500.00 EUR

                        Subtotal: 2000.00 EUR
                        Tax (19%): 380.00 EUR
                        Total: 2380.00 EUR
                        """,
                    "details": {"action": "invoke_agent", "source": "ocr_scanner"},
                }
            ]
        }
    )

    invoice_text: str = Field(
        ...,
        description="Unstructured invoice text from OCR or document extraction",
        examples=[""" Invoice #INV-2025-001
                Date: 2025-01-15
                Customer: Bechtle AG

                Line Items:
                1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr
                2. Software license - Qty: 1 @ 500.00 EUR

                Subtotal: 2000.00 EUR
                Tax (19%): 380.00 EUR
                Total: 2380.00 EUR
            """],
    )
    details: dict = Field(
        default_factory=dict,
        description="Additional details including action type",
        examples=[{"action": "invoke_agent", "source": "ocr_scanner"}],
    )
