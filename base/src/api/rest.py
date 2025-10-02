"""Generic RESTful API routes for the agent service (framework-level)."""

import logging
from http import HTTPStatus
from time import perf_counter
from typing import Any, Generic, Type, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel

from ..models import ProcessResourceResponse
from ..registry.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


# Define a TypeVar for the generic payload model
PayloadT = TypeVar("PayloadT", bound=BaseModel)


class RestApi(Generic[PayloadT]):
    """Generic OOP wrapper for the REST API router."""

    def __init__(self, payload_type: Type[PayloadT], registry: ServiceRegistry) -> None:
        self.router = APIRouter()
        self.payload_type = payload_type
        self._service_registry = registry
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
    ) -> ProcessResourceResponse | JSONResponse:
        """Generic endpoint for processing resources with illustrative payloads."""
        with tracer.start_as_current_span("api.process_resource") as span:
            request_id = str(uuid4())
            request.state.trace_id = request_id
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

                result = await self._service_registry.get_processing_service().process_rest_request(
                    payload, context
                )

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
            except HTTPException as exc:
                duration_ms = (perf_counter() - timer_start) * 1000
                span.record_exception(exc)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc.detail)))
                logger.warning(
                    "Resource processing raised HTTPException",
                    extra={
                        "request_id": request_id,
                        "duration_ms": round(duration_ms, 2),
                        "tenant_id": getattr(payload, "tenant_id", None),
                        "asset_id": getattr(payload, "asset_id", None),
                        "resource_type": getattr(payload, "resource_type", None),
                        "status_code": exc.status_code,
                    },
                    exc_info=True,
                )

                problem = self._build_problem_details(
                    status_code=exc.status_code,
                    detail=exc.detail,
                    instance=str(request.url),
                    trace_id=request_id,
                )

                return JSONResponse(
                    status_code=exc.status_code,
                    content=problem,
                    media_type="application/problem+json",
                    headers=exc.headers,
                )
            except Exception as e:
                duration_ms = (perf_counter() - timer_start) * 1000
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.record_exception(e)
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

                problem = self._build_problem_details(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e) or "Resource processing failed",
                    instance=str(request.url),
                    trace_id=request_id,
                )

                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content=problem,
                    media_type="application/problem+json",
                )

    @staticmethod
    def _build_problem_details(
        *,
        status_code: int,
        detail: Any,
        instance: str,
        trace_id: str,
        type_uri: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Normalize exceptions into RFC7807 problem detail documents."""

        problem: dict[str, Any]

        if isinstance(detail, dict):
            problem = detail.copy()
        else:
            problem = {"detail": str(detail) if detail is not None else ""}

        resolved_title = title or RestApi._resolve_status_title(status_code)

        problem.setdefault("type", type_uri or "about:blank")
        problem.setdefault("title", resolved_title)
        problem.setdefault("status", status_code)
        problem.setdefault("detail", "")
        problem.setdefault("instance", instance)
        problem.setdefault("traceId", trace_id)

        # Make sure types of required fields are correct
        problem["title"] = str(problem["title"])
        problem["detail"] = str(problem["detail"])
        problem["instance"] = str(problem["instance"])
        problem["traceId"] = str(problem["traceId"])
        problem["status"] = int(problem["status"])
        problem["type"] = str(problem["type"])

        return problem

    @staticmethod
    def _resolve_status_title(status_code: int) -> str:
        try:
            return HTTPStatus(status_code).phrase
        except ValueError:
            return "Unknown Error"
