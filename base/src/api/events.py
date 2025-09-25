"""Generic event-based API routes for the agent service (framework-level)."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel, Field, root_validator

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
router = APIRouter()


class CloudEvent(BaseModel):
    """CNCF CloudEvent 1.0 envelope."""

    specversion: str = Field(
        ...,
        description="CloudEvents spec version",
        examples=["1.0"],
    )
    id: str = Field(
        ...,
        description="Unique identifier for the event",
        examples=["evt-20240101-0001"],
    )
    source: str = Field(
        ...,
        description="URI reference that identifies the event producer",
        examples=["/services/asset-backup-checker"],
    )
    type: str = Field(
        ...,
        description="Type of event that occurred",
        examples=["asset.backup.completed"],
    )
    subject: Optional[str] = Field(
        default=None,
        description="Subject of the event in the context of the producer",
        examples=["asset-12345"],
    )
    time: Optional[datetime] = Field(
        default=None,
        description="Timestamp describing when the event occurred",
        examples=["2024-01-01T12:34:56Z"],
    )
    dataschema: Optional[str] = Field(
        default=None,
        description="A link to the schema that the data adheres to.",
    )
    datacontenttype: Optional[str] = Field(
        default=None,
        description="Content type of the event data",
        examples=["application/json"],
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Event payload expressed as JSON object.",
    )
    data_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded event payload (mutually exclusive with data).",
    )

    class Config:
        extra = "allow"
        schema_extra = {
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
                    "result": "success",
                    "details": {"snapshot_id": "snap-01", "duration_ms": 5230},
                },
            }
        }

    @root_validator(pre=True)
    def validate_spec_and_data(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        specversion = values.get("specversion")
        if specversion != "1.0":
            raise ValueError("Only CloudEvents specversion 1.0 is supported")

        has_data = "data" in values and values["data"] is not None
        has_data_base64 = "data_base64" in values and values["data_base64"] is not None

        if has_data and has_data_base64:
            raise ValueError("CloudEvent cannot include both 'data' and 'data_base64'")

        return values


class CloudEventResponse(BaseModel):
    """Response returned after generic CloudEvent processing."""

    status: str = Field(..., examples=["processed"])
    message: str = Field(..., examples=["Event processed successfully"])


@router.post(
    "/events/generic",
    response_model=CloudEventResponse,
    summary="Process a CNCF CloudEvent",
    responses={
        status.HTTP_200_OK: {
            "description": "CloudEvent accepted and processed",
            "content": {
                "application/json": {
                    "example": {
                        "status": "processed",
                        "message": "Event processed successfully",
                    }
                }
            },
        }
    },
)
async def handle_generic_event(
    request: Request,
    event: CloudEvent = Body(
        ...,
        example=CloudEvent.Config.schema_extra["example"],
    ),
) -> CloudEventResponse:
    """Generic event handler for processing CNCF CloudEvents."""
    with tracer.start_as_current_span("api.handle_generic_event") as span:
        span.set_attribute("cloudevents.specversion", event.specversion)
        span.set_attribute("cloudevents.type", event.type)
        span.set_attribute("cloudevents.source", event.source)
        if event.subject:
            span.set_attribute("cloudevents.subject", event.subject)

        tenant_id = getattr(event, "tenant_id", None) or getattr(event, "tenantId", None)

        logger.info(
            "CloudEvent received",
            extra={
                "cloudevents.id": event.id,
                "cloudevents.type": event.type,
                "cloudevents.source": event.source,
                "tenant_id": tenant_id,
                "path": request.url.path,
                "method": request.method,
            },
        )

        try:
            response = CloudEventResponse(
                status="processed",
                message="Event processed successfully",
            )
            logger.info(
                "CloudEvent processed",
                extra={
                    "cloudevents.id": event.id,
                    "cloudevents.type": event.type,
                    "tenant_id": tenant_id,
                    "response_message": response.message,
                },
            )
            return response
        except Exception as exc:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            logger.exception(
                "CloudEvent processing failed",
                extra={
                    "cloudevents.id": event.id,
                    "cloudevents.type": event.type,
                    "tenant_id": tenant_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Event processing failed",
            )
