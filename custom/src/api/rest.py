"""Custom REST API definition for the agent service."""

from pydantic import BaseModel, Field
from fastapi import Body
from base.src.api.rest import RestApi
from base.src.registry.service_registry import ServiceRegistry


class CustomPayload(BaseModel):
    """Define the expected payload for your custom REST endpoint."""

    tenant_id: str = Field(..., description="Tenant identifier", examples=["tenant-123"])
    asset_id: str = Field(..., description="Asset identifier", examples=["asset-456"])
    resource_type: str = Field(..., description="Type of the resource", examples=["backup", "server"])
    details: dict = Field(
        default_factory=dict,
        description="Additional details including action type",
        examples=[
            {
                "action": "invoke_agent",
                "description": "Analyze backup status for critical server",
                "priority": "high"
            }
        ]
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "tenant_id": "tenant-123",
                    "asset_id": "asset-456",
                    "resource_type": "backup",
                    "details": {
                        "action": "invoke_agent",
                        "description": "Analyze backup status for critical server",
                        "priority": "high"
                    }
                },
                {
                    "tenant_id": "tenant-789",
                    "asset_id": "asset-012",
                    "resource_type": "server",
                    "details": {
                        "action": "simple_process",
                        "description": "Quick status check",
                        "priority": "low"
                    }
                }
            ]
        }


class CustomRestApi(RestApi[CustomPayload]):
    """Custom REST API definition."""

    def __init__(self, registry: ServiceRegistry):
        super().__init__(payload_type=CustomPayload, registry=registry)
