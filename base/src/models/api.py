"""API-related data models for the agent service."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class CloudEventDataPayload(BaseModel):
    """Represents the `data` section of a CloudEvent."""

    tenant_id: Optional[str] = Field(
        default=None,
        alias="tenantId",
        description="Tenant identifier embedded in the event data.",
        examples=["tenant-42"],
    )
    asset_id: Optional[str] = Field(
        default=None,
        alias="assetId",
        description="Asset identifier referenced by the event data.",
        examples=["asset-12345"],
    )
    resource_type: Optional[str] = Field(
        default=None,
        alias="resourceType",
        description="Type of resource described in the payload.",
        examples=["database"],
    )
    correlation_id: Optional[str] = Field(
        default=None,
        alias="correlationId",
        description="Correlation identifier propagated across services.",
        examples=["7aa7f7b8-5ed9-4f43-bab3-d4a6e67f2fd5"],
    )
    result: Optional[str] = Field(
        default=None,
        description="Outcome reported by the event (if applicable).",
        examples=["success"],
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific details forwarded from the event.",
        examples=[{"snapshot_id": "snap-01", "duration_ms": 5230}],
    )
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional attributes included in the CloudEvent data.",
        examples=[{"region": "westeurope", "backup_enabled": True}],
    )
    model_config = ConfigDict(
        extra="allow",
        validate_by_name=True,
        json_schema_extra={
            "example": {
                "tenantId": "tenant-42",
                "assetId": "asset-12345",
                "resourceType": "database",
                "correlationId": ("7aa7f7b8-5ed9-4f43-bab3-d4a6e67f2fd5"),
                "result": "success",
                "details": {
                    "snapshot_id": "snap-01",
                    "duration_ms": 5230,
                },
                "attributes": {
                    "region": "westeurope",
                    "backup_enabled": True,
                },
            }
        },
    )


class CloudEventResponse(BaseModel):
    """Response returned after generic CloudEvent processing."""

    status: str = Field(..., examples=["processed"])
    message: str = Field(..., examples=["Event processed successfully"])


class ProcessResourceResponse(BaseModel):
    """Illustrative response for resource processing."""

    success: bool = Field(True, examples=[True])
    request_id: str = Field(
        ...,
        examples=["9f2c1f2e-09d8-4d0d-9b6f-2f6fef2ad87a"],
    )
    message: str = Field(
        ...,
        examples=["Processing completed successfully"],
    )


# --- Health Check Models ---


class LivenessResponse(BaseModel):
    """Response for the liveness probe."""

    status: str = Field(
        ..., description="Indicates the service is running.", examples=["UP"]
    )


class ComponentHealth(BaseModel):
    """Health status of a single downstream component."""

    status: str = Field(
        ...,
        description="Health status of the component.",
        examples=["healthy", "unhealthy"],
    )
    message: Optional[str] = Field(
        default=None,
        description="An optional message providing more details on the component's status.",
        examples=["Connection successful."],
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "message": "Connection to database successful.",
            }
        }
    )


class ReadinessResponse(BaseModel):
    """Response for the readiness probe, including downstream components."""

    status: str = Field(
        ...,
        description="Overall health status of the service.",
        examples=["UP", "DOWN"],
    )
    components: Dict[str, ComponentHealth] = Field(
        ...,
        description="Health status of individual components.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "UP",
                "components": {
                    "database": {
                        "status": "healthy",
                        "message": "Connection successful.",
                    },
                    "redis": {
                        "status": "unhealthy",
                        "message": "Failed to connect to endpoint.",
                    },
                },
            }
        }
    )
