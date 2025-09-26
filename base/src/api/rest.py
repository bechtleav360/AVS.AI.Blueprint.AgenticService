"""Generic RESTful API routes for the agent service (framework-level)."""

import logging
from time import perf_counter
from typing import Any, Dict, Generic, Optional, Type, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel

from ..models import ProcessResourceResponse
from ..services import processing_service

logger = logging.getLogger(__name__)


# Define a TypeVar for the generic payload model
PayloadT = TypeVar("PayloadT", bound=BaseModel)


class RestApi(Generic[PayloadT]):
    """Generic OOP wrapper for the REST API router."""

    def __init__(self, payload_type: Type[PayloadT]) -> None:
        self.router = APIRouter()
        self.payload_type = payload_type
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.post(
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
            payload: self.payload_type = Body(...),
        ) -> ProcessResourceResponse:
            return await self._process_resource(request, payload)

    async def _process_resource(
        self, request: Request, payload: PayloadT
    ) -> ProcessResourceResponse:
        """Generic endpoint for processing resources with illustrative payloads."""
        with tracer.start_as_current_span("api.process_resource") as span:
            request_id = str(uuid4())
            span.set_attribute("request_id", request_id)
            if hasattr(payload, "asset_id"):
                span.set_attribute("asset_id", getattr(payload, "asset_id"))
            if hasattr(payload, "tenant_id"):
                span.set_attribute("tenant_id", getattr(payload, "tenant_id"))

            timer_start = perf_counter()
            logger.info(
                "Processing resource request received",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "client_ip": request.client.host if request.client else None,
                    "payload": payload,
                },
            )

            try:
                # Process through the unified processing service
                context = {
                    "request_id": request_id,
                    "client_ip": request.client.host if request.client else None,
                }

                result = await processing_service.process_rest_request(payload, context)

                # Determine success based on processing result
                success = result["status"] == "processed"
                success_message = "Processing completed successfully"

                if result.get("processed_by"):
                    processors = ", ".join(result["processed_by"])
                    success_message = f"Processing completed by: {processors}"
                elif not success:
                    success_message = "No processor handled this request"

                response = ProcessResourceResponse(
                    success=success,
                    request_id=request_id,
                    message=success_message,
                )

                duration_ms = (perf_counter() - timer_start) * 1000
                logger.info(
                    "Resource processed",
                    extra={
                        "request_id": request_id,
                        "duration_ms": round(duration_ms, 2),
                        "tenant_id": getattr(payload, "tenant_id", None),
                        "asset_id": getattr(payload, "asset_id", None),
                        "resource_type": getattr(payload, "resource_type", None),
                        "response_message": response.message,
                        "success": success,
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
                        "tenant_id": getattr(payload, "tenant_id", None),
                        "asset_id": getattr(payload, "asset_id", None),
                        "resource_type": getattr(payload, "resource_type", None),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Resource processing failed",
                )


# This base router is no longer used directly; the custom API will be used instead.
# You can define a default instance for testing or simple cases if needed.
# from ..models import CloudEventDataPayload
# rest_api = RestApi(CloudEventDataPayload)
# router = rest_api.router
