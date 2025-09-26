"""Custom REST API definition for the agent service."""

from pydantic import BaseModel, Field
from base.src.api.rest import RestApi


class CustomPayload(BaseModel):
    """Define the expected payload for your custom REST endpoint."""

    tenant_id: str = Field(..., description="Tenant identifier")
    asset_id: str = Field(..., description="Asset identifier")
    resource_type: str = Field(..., description="Type of the resource")
    details: dict = Field(default_factory=dict, description="Additional details")


class CustomRestApi(RestApi[CustomPayload]):
    """Custom REST API definition."""

    def __init__(self):
        super().__init__(CustomPayload)
