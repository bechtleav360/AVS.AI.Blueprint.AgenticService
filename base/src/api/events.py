"""Event-driven API layer for the agent service."""

from __future__ import annotations

import logging
from datetime import datetime
from fastapi import APIRouter, Body, HTTPException, Request, status
from opentelemetry import trace

from ..models import CloudEventResponse
from ..models.events import GenericCloudEvent
from ..services import processing_service

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class CloudEventProcessor:
    """Encapsulates business logic executed for each CloudEvent."""

    async def process(self, event: GenericCloudEvent) -> CloudEventResponse:
        """Process a CloudEvent through the unified processing service."""
        try:
            result = await processing_service.process_event(event)
            
            if result["status"] == "processed":
                return CloudEventResponse(
                    status="processed",
                    message="Event processed successfully",
                )
            else:
                return CloudEventResponse(
                    status="no_processor",
                    message="No handler or agent processed this event",
                )
                
        except Exception as e:
            logger.error("CloudEvent processing failed: %s", str(e), exc_info=True)
            raise


class EventApi:
    """OOP wrapper that exposes the event-related FastAPI router."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self._processor = CloudEventProcessor()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.post(
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
            event: GenericCloudEvent = Body(
                ...,
                example=GenericCloudEvent.model_json_schema()["example"],
            ),
        ) -> CloudEventResponse:
            return await self._handle_generic_event(request, event)

    async def _handle_generic_event(
        self, request: Request, event: GenericCloudEvent
    ) -> CloudEventResponse:
        with tracer.start_as_current_span("api.handle_generic_event") as span:
            span.set_attribute("cloudevents.specversion", event.specversion)
            span.set_attribute("cloudevents.type", event.type)
            span.set_attribute("cloudevents.source", event.source)
            if event.subject:
                span.set_attribute("cloudevents.subject", event.subject)

            tenant_id = getattr(event, "tenant_id", None) or getattr(
                event, "tenantId", None
            )

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
                response = await self._processor.process(event)
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
                ) from exc


event_api = EventApi()
router = event_api.router
