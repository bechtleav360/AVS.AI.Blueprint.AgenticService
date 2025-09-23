"""Pydantic models for CloudEvents v1.0 specification."""

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID, uuid4

from pydantic import AnyUrl, BaseModel, Field

# Generic type for the CloudEvent data payload.
T = TypeVar("T")


class CloudEvent(BaseModel, Generic[T]):
    """
    A Pydantic model for a CloudEvent, compliant with the v1.0 spec.
    This model is generic and can be used with any data payload type.
    """

    # Required attributes
    spec_version: str = Field("1.0", alias="specversion", const=True)
    id: UUID = Field(default_factory=uuid4)
    source: AnyUrl
    type: str
    time: datetime = Field(default_factory=datetime.utcnow)

    # Optional attributes
    subject: Optional[str] = None
    data_content_type: Optional[str] = Field(None, alias="datacontenttype")
    data_schema: Optional[AnyUrl] = Field(None, alias="dataschema")
    data: Optional[T] = None

    class Config:
        # Allow population by field name OR alias.
        allow_population_by_field_name = True


# --- Helper Functions ---


def create_cloud_event(
    source: AnyUrl,
    type: str,
    data: Optional[Any] = None,
    **kwargs: Any,
) -> CloudEvent:
    """
    Create a new CloudEvent.

    This helper function simplifies the creation of a CloudEvent by automatically
    setting the required attributes and allowing optional attributes to be passed
    as keyword arguments.

    Args:
        source: The source of the event (a URI).
        type: The type of the event (e.g., 'com.example.item.created').
        data: The event payload (can be any Pydantic model or dict).
        **kwargs: Additional CloudEvent attributes (e.g., subject, data_content_type).

    Returns:
        A new CloudEvent instance.
    """
    if data is not None and "data_content_type" not in kwargs:
        kwargs["data_content_type"] = "application/json"

    return CloudEvent(source=source, type=type, data=data, **kwargs)
