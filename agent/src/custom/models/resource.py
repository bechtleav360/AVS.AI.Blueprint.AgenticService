"""Typed resource input model for the analyze_resource tool."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ResourceInput(BaseModel):
    """Generic resource description used by tools.

    Extend or replace this model in your domain as needed. Keeping a typed
    schema improves tool discoverability and validation.
    """

    id: Optional[str] = Field(
        default=None,
        description="Unique resource identifier (string)",
        examples=["asset-123", "vm-42"],
    )
    tags: Dict[str, str] = Field(
        default_factory=dict,
        description="Flat key/value tags used for basic classification",
        examples=[{"service-type": "web", "environment": "production"}],
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary properties describing the resource",
        examples=[["is_serverless", True], ["owner", "team-a"]],
    )
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Attributes used for scoring and compliance checks",
        examples=[["encryption_enabled", True], ["public_access", False]],
    )
