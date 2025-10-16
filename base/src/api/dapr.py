"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, status
from opentelemetry import trace

from ..models.events import CloudEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class DaprApi:
    """Encapsulates all Dapr-related endpoints and logic."""

    def __init__(self, component_registry: "ComponentRegistry"):
        self._component_registry = component_registry
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self):
        self.router.add_api_route(
            "/dapr/subscribe", self.dapr_subscribe, methods=["GET"]
        )
        self.router.add_api_route(
            "/events/{topic}", self.handle_dapr_event, methods=["POST"]
        )

    async def dapr_subscribe(self) -> List[Dict[str, Any]]:
        """
        Dapr subscription discovery endpoint.

        Implementations can override this by adding their own router with the same
        path to provide real topics and routes.
        """
        # Framework default: no subscriptions declared.
        # Example structure:
        # return [
        #     {"pubsubname": "pubsub", "topic": "events.topic1", "route": "/events/topic1"}
        # ]
        return []

    async def handle_dapr_event(self, topic: str, request: Request) -> Dict[str, Any]:
        """
        Generic Dapr event handler that processes events through the unified service.
        """
        with tracer.start_as_current_span("dapr.handle_event") as span:
            span.set_attribute("dapr.topic", topic)
            try:
                payload = await request.json()
                logger.debug("Received Dapr event on topic %s", topic)

                # Check if payload is already a CloudEvent
                if self._is_cloudevent(payload):
                    logger.debug("Payload is already a CloudEvent, using as-is")
                    cloud_event = CloudEvent(**payload)
                else:
                    # Wrap non-CloudEvent payload in CloudEvent format
                    logger.debug("Wrapping payload in CloudEvent format")
                    cloud_event = CloudEvent(
                        specversion="1.0",
                        id=payload.get("id", f"dapr-{topic}"),
                        source=f"/dapr/topic/{topic}",
                        type=f"dapr.{topic}",
                        data=payload,
                    )

                # Process through the unified service
                processing_service = self._component_registry.get_processing_service()
                context = {"dapr_topic": topic}
                result_event = await processing_service.process_event(
                    cloud_event, context
                )

                # Return Dapr-compatible response based on result event
                if result_event.data.get("status") == "processed":
                    return {"status": "SUCCESS"}
                else:
                    logger.warning("No processor handled Dapr event on topic %s", topic)
                    return {
                        "status": "SUCCESS"
                    }  # Still return SUCCESS to avoid retries

            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                logger.error("Dapr event handling failed: %s", str(e), exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Dapr event handling failed",
                )

    def _is_cloudevent(self, payload: Dict[str, Any]) -> bool:
        """
        Check if a payload is already a CloudEvent.

        Args:
            payload: The payload to check

        Returns:
            True if payload contains CloudEvent required fields
        """
        # CloudEvents 1.0 required fields
        required_fields = {"specversion", "id", "source", "type"}
        return required_fields.issubset(payload.keys())
