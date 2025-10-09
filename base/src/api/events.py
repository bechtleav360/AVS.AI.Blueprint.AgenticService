"""Event-driven API layer for the agent service."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Body, HTTPException, Request, status
from opentelemetry import trace

from ..models import CloudEventResponse
from ..models.events import GenericCloudEvent
from ..registry.component_registry import ComponentRegistry
from ..services.processing_service import ProcessingService

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class EventApi:
    """OOP wrapper that exposes the event-related FastAPI router."""

    def __init__(self, component_registry: ComponentRegistry) -> None:
        self.router = APIRouter()
        self._component_registry = component_registry
        # Create processing service with the component registry
        self._processing_service = ProcessingService(
            settings=component_registry.get_settings(),
            component_registry=component_registry,
        )
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

            logger.info(
                "CloudEvent received",
                extra={
                    "cloudevents.id": event.id,
                    "cloudevents.type": event.type,
                    "cloudevents.source": event.source,
                    "path": request.url.path,
                    "method": request.method,
                },
            )

            try:
                result = await self._processing_service.process_event(event)

                if result["status"] == "processed":
                    response = CloudEventResponse(
                        status="processed",
                        message="Event processed successfully",
                    )
                else:
                    response = CloudEventResponse(
                        status="no_processor",
                        message="No handler or agent processed this event",
                    )

                logger.info(
                    "CloudEvent processed successfully",
                    extra={
                        "cloudevents.id": event.id,
                        "cloudevents.type": event.type,
                        "response_message": response.message,
                    },
                )
                return response
            except Exception as exc:
                logger.exception(
                    "CloudEvent processing failed",
                    extra={
                        "cloudevents.id": event.id,
                        "cloudevents.type": event.type,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Event processing failed",
                ) from exc


# Removed singleton pattern - EventApi should be instantiated in app_builder
