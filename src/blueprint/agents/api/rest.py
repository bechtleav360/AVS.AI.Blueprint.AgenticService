"""Generic RESTful API routes for the agent service (framework-level)."""

import logging
from http import HTTPStatus
from time import perf_counter
from typing import Any, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel

from ..models import ProcessResourceResponse
from ..registry.component_registry import ComponentRegistry
from ..services.processing_service import ProcessingService

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Define a TypeVar for the generic payload model
PayloadT = TypeVar('PayloadT', bound=BaseModel)

class RestApi:
    """Generic OOP wrapper for the REST API router."""

    def __init__(self, payload_type: type[PayloadT], registry: ComponentRegistry) -> None:
        self.router = APIRouter()
        self.payload_type = payload_type
        self._component_registry = registry
        # Create processing service with the component registry
        self._processing_service = ProcessingService(settings=registry.get_settings(), component_registry=registry)
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

    async def _process_resource(self, request: Request, payload: PayloadT) -> ProcessResourceResponse | JSONResponse:
        """Generic endpoint for processing resources with illustrative payloads."""
        with tracer.start_as_current_span("api.process_resource") as span:
            request_id = str(uuid4())
            request.state.trace_id = request_id
            span.set_attribute("request_id", request_id)
            # Add payload attributes to span if available
            for attr in ["id", "tenant_id", "asset_id", "invoice_id", "resource_id"]:
                if hasattr(payload, attr):
                    span.set_attribute(f"payload.{attr}", getattr(payload, attr))

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

                result_event = await self._processing_service.process_rest_request(payload, context)

                # Extract result data from CloudEvent
                result = result_event.data

                # Determine success based on processing result
                success = result["status"] == "processed"
                success_message = "Processing completed successfully"

                if result.get("processed_by"):
                    processors = ", ".join(result["processed_by"])
                    success_message = f"Processing completed by: {processors}"
                elif not success:
                    success_message = "No processor handled this request"

                # Extract agent result if available
                agent_result = result.get("agent_result")
                response_data = None
                if agent_result:
                    # Convert Pydantic model to dict if needed
                    if hasattr(agent_result, "model_dump"):
                        response_data = agent_result.model_dump()
                    elif hasattr(agent_result, "dict"):
                        response_data = agent_result.dict()
                    else:
                        response_data = agent_result

                response = ProcessResourceResponse(
                    success=success,
                    request_id=request_id,
                    message=success_message,
                    data=response_data,
                )

                duration_ms = (perf_counter() - timer_start) * 1000
                logger.info(
                    "Resource processed",
                    extra={
                        "request_id": request_id,
                        "duration_ms": round(duration_ms, 2),
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
