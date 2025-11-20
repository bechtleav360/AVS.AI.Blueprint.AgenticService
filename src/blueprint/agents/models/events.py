"""Pydantic models for CloudEvents v1.0 specification."""

from datetime import datetime, UTC
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.config import ConfigDict

# Generic type for the CloudEvent data payload.
T = TypeVar("T")


class CloudEvent(BaseModel, Generic[T]):
    """
    A Pydantic model for a CloudEvent, compliant with the v1.0 spec.
    This model is generic and can be used with any data payload type.
    """

    # Required attributes
    id: str = Field(..., description="Unique identifier for the event")
    type: str = Field(..., description="Type of event that occurred")

    # Optional attributes
    specversion: Literal["1.0"] | None = Field("1.0", description="CloudEvents spec version")
    source: str | None = Field(None, description="URI reference that identifies the event producer.")
    subject: str | None = Field(None, description="Subject of the event")
    time: str | None = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        description="Timestamp of the event in ISO 8601 format with 'Z' timezone indicator",
    )
    datacontenttype: str | None = Field(None, description="Content type of the data")
    dataschema: str | None = Field(None, description="Schema of the data")
    data: T | None = Field(None, description="Event payload")
    data_base64: str | None = Field(None, description="Base64-encoded event payload")

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

    @field_validator("time")
    def validate_time_format(cls, v):
        """Validate that the time is in ISO 8601 format with timezone."""
        if not isinstance(v, str):
            raise ValueError("Time must be a string in ISO 8601 format")
        try:
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                raise ValueError("Time must include timezone information")
            return v
        except ValueError as e:
            raise ValueError("Time must be in ISO 8601 format with timezone") from e

    @model_validator(mode="before")
    def validate_data_exclusivity(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that CloudEvent cannot include both 'data' and 'data_base64'."""
        if values.get("data") is not None and values.get("data_base64") is not None:
            raise ValueError("CloudEvent cannot include both 'data' and 'data_base64'")
        return values


# A generic CloudEvent for use in API layers, accepting any JSON payload.
GenericCloudEvent = CloudEvent[dict[str, Any]]


class HandlerResult(BaseModel):
    """Standardized result emitted by event handlers."""

    event_type: str | None = None
    subject: str | None = None
    data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
