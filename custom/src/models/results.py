"""Custom result models for the agent outputs."""

from typing import Any

from pydantic import BaseModel, Field


class CustomAgentOutput(BaseModel):
    """Simplified agent output compatible with vLLM schema constraints.

    Uses flat structure to avoid $defs references that vLLM doesn't support.
    """

    resource_id: str = Field(..., description="The unique identifier of the analyzed resource")
    status: str = Field(..., description="The determined status (e.g., 'processed', 'failed')")
    summary: str = Field(..., description="A brief summary of the analysis")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    notes: str | None = Field(None, description="Additional notes or details")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")
