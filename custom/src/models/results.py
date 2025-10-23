"""Custom result models for the agent outputs."""

from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from .asset import AssetHarmonizingOutput


class AssetTaggingOutput(BaseModel):
    """LLM classification output following the exact required JSON schema.

    Output format (strict JSON only). Always produce this exact schema:
    {
      "category": { "code": "A0X" or "UNKNOWN", "name": "..." },
      "confidence": 0.0-1.0,
      "ambiguous": true/false,
      "rationale": ["short explanation of why this category was chosen (3-4 bullet points or a short sentence).", ... ],
      "matched_fields": [ "name", "description", "tags", "hardwareExtension.model", ... ],
      "missing_data": [ list of fields that would increase confidence, e.g. "type","softwareExtension.licenseType","providerExtension.serviceCategory" ],
      "recommended_next_steps": [ short actionable items, e.g. "ask for device model", "check vendor docs", "request screenshots" ]
    }

    Use the `to_strict_json()` helper to produce the exact JSON-compatible dict.
    """

    class Category(BaseModel):
        code: str = Field(..., description='Category code (e.g. "A0X" or "UNKNOWN")')
        name: str = Field(..., description="Human-readable category name")

    category: Category = Field(..., description="Category object with code and name")
    ambiguous: bool = Field(..., description="Whether the classification is ambiguous")
    rationale: list[str] = Field(
        ...,
        description="Short explanation of why this category was chosen (3-4 bullet points or a short sentence).",
    )

    matched_fields: list[str] = Field(
        ..., description='List of matched fields (e.g., "name", "description", "tags")'
    )
    missing_data: list[str] = Field(
        ..., description='List of fields that would increase confidence if provided'
    )
    recommended_next_steps: list[str] = Field(
        ..., description='Actionable next steps (short items)'
    )

    def to_strict_json(self) -> dict:
        """
        Return a JSON-serializable dict that exactly matches the required schema.
        Use this for producing output to the caller or for serialization.
        """
        return {
            "category": {"code": self.category.code, "name": self.category.name},
            "confidence": self.confidence,
            "ambiguous": bool(self.ambiguous),
            "rationale": list(self.rationale),
            "matched_fields": list(self.matched_fields),
            "missing_data": list(self.missing_data),
            "recommended_next_steps": list(self.recommended_next_steps),
        }

    # model_config = ConfigDict(json_encoders={Decimal: lambda value: str(value)})

    # status: str = Field(
    #     ...,
    #     description="The determined status (e.g., 'valid', 'invalid', 'incomplete')",
    # )
    # summary: str = Field(..., description="A brief summary of the invoice analysis")
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )
    # notes: str | None = Field(None, description="Additional notes or details")
    # metadata: dict[str, Any] | None = Field(None, description="Additional metadata")

class HandlerResult(BaseModel):
    """Base result model for handler outputs.

    Handlers should return this model (or None to continue chain).
    If event_type is provided, a new event will be published automatically.
    """

    data: Any = Field(..., description="The result data from processing")
    event_type: Optional[str] = Field(
        None,
        description="Optional event type to publish. If provided, triggers event publishing.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata for the result"
    )


class HarmonizingOutput(BaseModel):
    """Output from the harmonizing agent.

    Contains the harmonized Asset plus metadata about the harmonization process.
    """

    asset: AssetHarmonizingOutput = Field(..., description="The harmonized asset")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="List of warnings or issues encountered during harmonization",
    )
    mapped_fields: list[str] = Field(
        default_factory=list,
        description="List of source fields that were successfully mapped",
    )
