"""Data Transfer Objects (DTOs) for REST API endpoints."""

from pydantic import BaseModel, Field


class CustomPayload(BaseModel):
    """Define the expected payload for asset tagging endpoint.

    Accepts unstructured text (e.g., from OCR) that the agent will parse and analyze.
    """

    asset: dict = Field(
        default_factory=dict,
        description="Additional details including action type",
        examples=[{"id": "1000", "name":"SAP LeanIX"}],
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
                    "asset": {"id": 1000, "name":"SAP LeanIX"},
                    "details": {"action": "invoke_agent", "source": "ocr_scanner"},
                }
            ]
        }
