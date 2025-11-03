"""Asset models for harmonizing agent.

These models define the canonical Asset schema used by the harmonizing agent.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AssetType:
    """Asset type constants."""

    SOFTWARE = "software"
    HARDWARE = "hardware"


class AssetStatus:
    """Asset status constants."""

    DRAFT = "draft"
    UNTAGGED = "untagged"
    UNSCORED = "unscored"
    SCORED = "scored"


class Reference(BaseModel):
    """Reference to another asset."""

    id: Optional[str] = Field(None, description="Referenced asset ID")
    relation: Optional[str] = Field(
        None, description="Relationship (e.g., dependsOn, providedBy)"
    )


class HardwareExtension(BaseModel):
    """Hardware-specific extension fields."""

    manufacturer: Optional[str] = Field(None, description="name of the manufacturer")
    model: Optional[str] = Field(None, description="hardware model description")


class SoftwareExtension(BaseModel):
    """Software-specific extension fields."""

    manufacturer: Optional[str] = Field(None, description="name of the manufacturer")
    version: Optional[str] = Field(None, description="software version")
    licenseType: Optional[str] = Field(
        None, description="software's license type"
    )


class AssetHarmonizingOutput(BaseModel):
    """Canonical Asset schema for harmonized data.

    This is the unified schema that all source data is harmonized into.
    """

    # Basic fields
    id: Optional[str] = Field(None, description="the asset's ID")
    name: Optional[str] = Field(None, description="name of the asset")
    description: Optional[str] = Field(
        None, description="further description of the asset"
    )
    type: Optional[
        Literal[
            AssetType.SOFTWARE,
            AssetType.HARDWARE,
        ]
    ] = Field(None, description="overall type of asset")

    externalId: Optional[Dict[str, str]] = Field(
        default=None,
        description="identifiers from source systems (key: source system, value: external ID)",
    )
    status: Optional[
        Literal[
            AssetStatus.DRAFT,
            AssetStatus.UNTAGGED,
            AssetStatus.UNSCORED,
            AssetStatus.SCORED,
        ]
    ] = Field(None, description="current status of this asset")

    # After-harmonizing policy: these must be null
    tags: Optional[List[str]] = Field(
        default=None,
        description="list of tags associated with this asset (null after harmonizing)",
    )
    references: Optional[List[Reference]] = Field(
        default=None,
        description="references to other assets (null after harmonizing)",
    )
    additionalProperties: Optional[Dict[str, Any]] = Field(
        default=None, description="Dictionary of unprocessed source properties"
    )

    # Extensions
    hardware: Optional[HardwareExtension] = None
    software: Optional[SoftwareExtension] = None

    def to_json(self) -> Dict[str, Any]:
        """Return a JSON-ready dict with extension fields flattened to top level.

        - Excludes None values.
        - Merges fields from `hardware` and `software` into the root level.
        """
        data: Dict[str, Any] = self.model_dump(exclude_none=True)

        # Extract and flatten extension fields
        for ext_name in ("hardware", "software"):
            ext = data.pop(ext_name, None)
            if isinstance(ext, dict):
                # Merge extension fields into the top-level dict
                data.update(ext)

        return data
