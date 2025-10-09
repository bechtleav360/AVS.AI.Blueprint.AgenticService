"""Custom REST API definition for the agent service."""

from fastapi import Body
from pydantic import BaseModel, Field

from base.src.api.rest import RestApi
from base.src.registry.component_registry import ComponentRegistry
from base.src.services.processing_service import ProcessingService


class CustomPayload(BaseModel):
    """Define the expected payload for invoice processing endpoint.
    
    Accepts unstructured text (e.g., from OCR) that the agent will parse and analyze.
    """

    invoice_text: str = Field(
        ...,
        description="Unstructured invoice text from OCR or document extraction",
        examples=[
            """Invoice #INV-2025-001
Date: 2025-01-15
Customer: Bechtle AG

Line Items:
1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr
2. Software license - Qty: 1 @ 500.00 EUR

Subtotal: 2000.00 EUR
Tax (19%): 380.00 EUR
Total: 2380.00 EUR"""
        ],
    )
    details: dict = Field(
        default_factory=dict,
        description="Additional details including action type",
        examples=[{"action": "invoke_agent", "source": "ocr_scanner"}],
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "invoice_text": """Invoice #INV-2025-001
Date: 2025-01-15
Customer: Bechtle AG

Line Items:
1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr
2. Software license - Qty: 1 @ 500.00 EUR

Subtotal: 2000.00 EUR
Tax (19%): 380.00 EUR
Total: 2380.00 EUR""",
                    "details": {"action": "invoke_agent", "source": "ocr_scanner"},
                }
            ]
        }


class CustomRestApi(RestApi[CustomPayload]):
    """Custom REST API definition."""

    def __init__(self, registry: ComponentRegistry):
        super().__init__(payload_type=CustomPayload, registry=registry)
