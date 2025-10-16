"""Custom result models for the agent outputs."""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InvoiceAnalysisOutput(BaseModel):
    """Invoice analysis output compatible with vLLM schema constraints.

    Uses flat structure to avoid $defs references that vLLM doesn't support.
    """

    model_config = ConfigDict(json_encoders={Decimal: lambda value: str(value)})

    invoice_id: str = Field(..., description="The unique identifier of the invoice")
    status: str = Field(
        ...,
        description="The determined status (e.g., 'valid', 'invalid', 'incomplete')",
    )
    summary: str = Field(..., description="A brief summary of the invoice analysis")
    total_amount: Decimal = Field(..., description="Total invoice amount (sum of line items)")
    inferred_tax_amount: Decimal = Field(..., description="Inferred or calculated tax amount")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    notes: str | None = Field(None, description="Additional notes or details")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")
