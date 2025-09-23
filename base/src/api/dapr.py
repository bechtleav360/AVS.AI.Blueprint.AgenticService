"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, status
from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
router = APIRouter()


@router.get("/dapr/subscribe")
async def dapr_subscribe() -> List[Dict[str, Any]]:
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


@router.post("/events/{topic}")
async def handle_dapr_event(topic: str, request: Request) -> Dict[str, Any]:
    """
    Generic Dapr event handler placeholder.

    Implementations should override with domain logic. This default handler just
    acknowledges the event.
    """
    with tracer.start_as_current_span("dapr.handle_event") as span:
        span.set_attribute("dapr.topic", topic)
        try:
            payload = await request.json()
            logger.info(f"Received Dapr event on topic '{topic}': {payload}")
            return {"status": "SUCCESS"}
        except Exception as e:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Dapr event handling failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Dapr event handling failed",
            )
