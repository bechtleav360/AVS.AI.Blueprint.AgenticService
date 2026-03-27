"""Generic RESTful API base class for the agent service (framework-level).

Subclasses register routes by decorating methods the class-level HTTP verb helpers.

Example::

    class MyApi(RestApiBase):
        def __init__(self) -> None:
            super().__init__()

            tags=["Status"],
        @RestApiBase.get("/items", response_model=list[Item], tags=["Items"], summary="Get for Items")
        async def list_items(self) -> list[Item]:
            return await self.get_registry().get_service("item_service").all()

        @RestApiBase.post("/items", response_model=Item, tags=["Items"], summary="Create for Items")
        async def create_item(self, payload: ItemRequest) -> Item:
            return await self.get_registry().get_service("item_service").create(payload)
"""

from __future__ import annotations

import logging

from abc import ABC
from http import HTTPStatus
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from opentelemetry import trace

from ...component.component import traced
from ...models import ProcessResourceResponse
from ..io_base import IOBase

logger = logging.getLogger(__name__)


class RestApiBase(IOBase, ABC):
    """Base class for REST API components.

    Routes are registered by decorating methods with the class-level HTTP verb
    helpers (``RestApiBase.get``, ``RestApiBase.post``, ``RestApiBase.put``,
    ``RestApiBase.delete``, ``RestApiBase.patch``).  The base class wires those
    decorated methods onto ``self.router`` during ``__init__``, so subclasses
    never need to call ``_wire_routes()`` or touch the router directly.
    """

    def __init__(self, should_register: bool = True) -> None:
        super().__init__(should_register)
        self._router = APIRouter()
        self._wire_routes()

    @property
    def router(self) -> APIRouter:
        """Access the instance router. This property is read-only."""

        return self._router

    @staticmethod
    def get(path: str, **kwargs: Any):
        """Decorator: register a GET route on the instance router."""

        def decorator(func):
            func._route = ("get", path, kwargs)
            return func

        return decorator

    @staticmethod
    def post(path: str, **kwargs: Any):
        """Decorator: register a POST route on the instance router."""

        def decorator(func):
            func._route = ("post", path, kwargs)
            return func

        return decorator

    @staticmethod
    def put(path: str, **kwargs: Any):
        """Decorator: register a PUT route on the instance router."""

        def decorator(func):
            func._route = ("put", path, kwargs)
            return func

        return decorator

    @staticmethod
    def delete(path: str, **kwargs: Any):
        """Decorator: register a DELETE route on the instance router."""

        def decorator(func):
            func._route = ("delete", path, kwargs)
            return func

        return decorator

    @staticmethod
    def patch(path: str, **kwargs: Any):
        """Decorator: register a PATCH route on the instance router."""

        def decorator(func):
            func._route = ("patch", path, kwargs)
            return func

        return decorator

    def _wire_routes(self) -> None:
        """Discover and register all decorated route methods on self.router."""

        seen: set[str] = set()
        for cls in type(self).__mro__:
            for name, obj in cls.__dict__.items():
                if name in seen:
                    continue
                seen.add(name)
                if callable(obj) and hasattr(obj, "_route"):
                    verb, path, kwargs = obj._route
                    getattr(self.router, verb)(path, **kwargs)(getattr(self, name))

    @traced()
    async def _process_resource(self, request: Request, payload: Any) -> ProcessResourceResponse | JSONResponse:
        """Generic endpoint for processing resources with illustrative payloads."""
        span = trace.get_current_span()
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

            result_event = await self.registry.event_processing_service.process_rest_request(payload, context)

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

        resolved_title = title or RestApiBase._resolve_status_title(status_code)

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
