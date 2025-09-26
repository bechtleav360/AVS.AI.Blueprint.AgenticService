"""Pydantic models for CloudEvents v1.0 specification."""

from datetime import datetime
from typing import Any, Dict, Generic, Literal, Optional, TypeVar
from uuid import UUID, uuid4

from pydantic import AnyUrl, BaseModel, Field, root_validator
from pydantic.config import ConfigDict

# Generic type for the CloudEvent data payload.
T = TypeVar("T")


class CloudEvent(BaseModel, Generic[T]):
    """
    A Pydantic model for a CloudEvent, compliant with the v1.0 spec.
    This model is generic and can be used with any data payload type.
    """

    # Required attributes
    specversion: Literal["1.0"] = Field("1.0", description="CloudEvents spec version")
    id: str = Field(..., description="Unique identifier for the event")
    source: str = Field(..., description="URI reference that identifies the event producer")
    type: str = Field(..., description="Type of event that occurred")

    # Optional attributes
    subject: Optional[str] = Field(None, description="Subject of the event")
    time: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Timestamp of the event")
    datacontenttype: Optional[str] = Field(None, description="Content type of the data")
    dataschema: Optional[str] = Field(None, description="Schema of the data")
    data: Optional[T] = Field(None, description="Event payload")
    data_base64: Optional[str] = Field(None, description="Base64-encoded event payload")

    model_config = ConfigDict(
        extra="allow",
        validate_by_name=True,
        json_schema_extra={
            "example": {
                "specversion": "1.0",
                "id": "evt-20240101-0001",
                "type": "asset.backup.completed",
                "source": "/services/asset-backup-checker",
                "subject": "asset-12345",
                "time": "2024-01-01T12:34:56Z",
                "datacontenttype": "application/json",
                "data": {
                    "tenantId": "tenant-42",
                    "assetId": "asset-12345",
                },
            }
        },
    )

    @root_validator(pre=True)
    def validate_data_exclusivity(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get("data") is not None and values.get("data_base64") is not None:
            raise ValueError("CloudEvent cannot include both 'data' and 'data_base64'")
        return values


# A generic CloudEvent for use in API layers, accepting any JSON payload.
GenericCloudEvent = CloudEvent[Dict[str, Any]]
