"""Pydantic models for CloudEvents v1.0 specification."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.config import ConfigDict


class CloudEvent[T](BaseModel):
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
    topic: str | None = Field(None, description="Topic of the event")

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
    @classmethod
    def validate_time_format(cls, v: str | None) -> str | None:
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
    @classmethod
    def validate_data_exclusivity(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that CloudEvent cannot include both 'data' and 'data_base64'."""
        if values.get("data") is not None and values.get("data_base64") is not None:
            raise ValueError("CloudEvent cannot include both 'data' and 'data_base64'")
        return values


# A generic CloudEvent for use in API layers, accepting any JSON payload.
GenericCloudEvent = CloudEvent[dict[str, Any]]


class HandlerResult(BaseModel):
    """Standardized result emitted by event handlers.

    Handlers can return:
    - A single HandlerResult to publish one event
    - A list of HandlerResult objects to publish multiple events
    - ``HandlerResult.skipped(reason)`` when the handler is responsible for the event but the
      event needs nothing: the chain stops, the delivery is acknowledged and the reason is logged
    - None to pass control to the next handler
    - Any other value for internal chaining (no event publication)
    """

    event_type: str | None = None
    subject: str | None = None
    data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    skip_reason: str | None = None

    @model_validator(mode="after")
    def _skip_carries_nothing_else(self) -> "HandlerResult":
        """A skipped result publishes nothing and returns nothing, so it may carry only its reason.

        Without this, ``HandlerResult(event_type="x", skip_reason="y")`` would be both published and
        reported as skipped, and nobody could tell from the result which of the two the author meant.
        """
        if self.skip_reason is not None:
            if not self.skip_reason.strip():
                raise ValueError("HandlerResult.skip_reason must name why the event needs nothing, not be empty")
            if self.event_type is not None or self.subject is not None or self.data is not None:
                raise ValueError("A skipped HandlerResult carries only its reason (and metadata), never event_type, subject or data")
        return self

    @classmethod
    def skipped(cls, reason: str, *, metadata: dict[str, Any] | None = None) -> "HandlerResult":
        """Return the result of a handler that is responsible for the event but finds it needs nothing.

        This is the answer of the handler that *was* selected: the chain stops here and offers the
        event to no other handler, the transport acknowledges it, and the reason is logged at INFO
        and counted as ``blueprint.events.skipped``. Return ``None`` instead only when another
        handler should get the event; an event no handler is selected for keeps the WARNING.

        Args:
            reason: Why the event needs nothing, e.g. ``"status unchanged"``. Logged; keep personal
                data and secrets out of it.
            metadata: Optional values kept on the processing result for the caller; never published.
        """
        return cls(skip_reason=reason, metadata=metadata)

    @property
    def is_skipped(self) -> bool:
        """Whether this is a :meth:`skipped` result."""
        return self.skip_reason is not None


def create_cloud_event(
    event_type: str,
    data: BaseModel | dict[str, Any],
    *,
    source: str | None = None,
    subject: str | None = None,
    event_id: str | None = None,
) -> GenericCloudEvent:
    """Create a GenericCloudEvent from a domain payload.

    Convenience factory that handles Pydantic model serialization and
    ID generation, reducing boilerplate when constructing events from
    REST endpoints or service code.

    Args:
        event_type: The CloudEvent ``type`` field (e.g., ``"order.created"``).
        data: Event payload — a Pydantic model (auto-dumped to dict) or a plain dict.
        source: URI reference identifying the event producer. Defaults to ``"/api"``.
        subject: Optional subject of the event.
        event_id: Optional explicit event ID. A UUID is generated if omitted.

    Returns:
        A fully populated :class:`GenericCloudEvent`.
    """
    payload = data.model_dump() if isinstance(data, BaseModel) else data
    return GenericCloudEvent(
        id=event_id or str(uuid4()),
        type=event_type,
        source=source or "/api",
        subject=subject,
        data=payload,
    )
