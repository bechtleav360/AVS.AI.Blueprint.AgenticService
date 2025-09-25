"""Generic RESTful API routes for the agent service (framework-level)."""

import logging
from time import perf_counter
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
router = APIRouter()


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

    class Config:
        extra = "allow"
        allow_population_by_field_name = True
        schema_extra = {
            "example": {
                "tenantId": "tenant-42",
                "assetId": "asset-12345",
                "resourceType": "database",
                "correlationId": (
                    "7aa7f7b8-5ed9-4f43-bab3-d4a6e67f2fd5"
                ),
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
        }


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


@router.post(
    "/process-resource",
    response_model=ProcessResourceResponse,
    summary="Trigger resource processing",
    responses={
        status.HTTP_200_OK: {
            "description": "Processing completed",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "request_id": "9f2c1f2e-09d8-4d0d-9b6f-2f6fef2ad87a",
                        "message": "Processing completed successfully",
                    }
                }
            },
        }
    },
)
async def process_resource(
    request: Request,
    payload: CloudEventDataPayload = Body(
        ...,
        example=CloudEventDataPayload.Config.schema_extra["example"],
    ),
) -> ProcessResourceResponse:
    """Generic endpoint for processing resources with illustrative payloads."""
    with tracer.start_as_current_span("api.process_resource") as span:
        request_id = str(uuid4())
        span.set_attribute("request_id", request_id)
        if payload.asset_id:
            span.set_attribute("asset_id", payload.asset_id)
        if payload.tenant_id:
            span.set_attribute("tenant_id", payload.tenant_id)

        timer_start = perf_counter()
        logger.info(
            "Processing resource request received",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "client_ip": request.client.host if request.client else None,
                "tenant_id": payload.tenant_id,
                "asset_id": payload.asset_id,
                "resource_type": payload.resource_type,
                "correlation_id": payload.correlation_id,
                "result": payload.result,
                "attributes": payload.attributes,
            },
        )

        try:
            success_message = "Processing completed successfully"
            if payload.result:
                success_message = f"Processing completed: {payload.result}"

            response = ProcessResourceResponse(
                success=True,
                request_id=request_id,
                message=success_message,
            )
            duration_ms = (perf_counter() - timer_start) * 1000
            logger.info(
                "Resource processed successfully",
                extra={
                    "request_id": request_id,
                    "duration_ms": round(duration_ms, 2),
                    "tenant_id": payload.tenant_id,
                    "asset_id": payload.asset_id,
                    "resource_type": payload.resource_type,
                    "response_message": response.message,
                },
            )
            return response
        except Exception as e:
            duration_ms = (perf_counter() - timer_start) * 1000
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.exception(
                "Resource processing failed",
                extra={
                    "request_id": request_id,
                    "duration_ms": round(duration_ms, 2),
                    "tenant_id": payload.tenant_id,
                    "asset_id": payload.asset_id,
                    "resource_type": payload.resource_type,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Resource processing failed",
            )
