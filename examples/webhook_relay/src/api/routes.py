"""REST endpoints for the webhook relay service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.eventing.event_processing_service import (
    EventProcessingService,
)

from ..models.schemas import WebhookPayload
from ..services.webhook_service import WebhookService

logger = logging.getLogger(__name__)


class WebhookApi(RestApiBase):
    """Provides HTTP endpoints for ingesting and querying webhooks."""

    def __init__(self) -> None:
        super().__init__()

    async def on_startup(self) -> None:
        """Resolve the services this API delegates to."""
        self._events = self.registry.get_service(EventProcessingService)
        self._webhooks = self.registry.get_service(WebhookService)

    async def on_shutdown(self) -> None:
        """No API-specific shutdown needed."""

    @RestApiBase.post(
        "/webhooks",
        summary="Receive a webhook",
        tags=["Webhooks"],
    )
    async def receive_webhook(self, payload: WebhookPayload, request: Request) -> JSONResponse:
        """Accept a raw webhook POST and feed it through the handler chain."""
        webhook_id = payload.webhook_id or str(uuid4())

        # Build a CloudEvent to drive the handler chain
        cloud_event = GenericCloudEvent(
            id=webhook_id,
            type="webhook.received",
            source=f"/webhooks/{payload.source}",
            subject=payload.event_type,
            time=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            data=payload.model_dump(),
        )

        processing = await self._events.process_event(cloud_event)
        results = [result.data for result in processing.result if result.data is not None]

        return JSONResponse(
            status_code=202,
            content={
                "status": processing.status.value,
                "webhook_id": webhook_id,
                "message": processing.message,
                "result": results[0] if results else None,
            },
        )

    @RestApiBase.get(
        "/webhooks/recent",
        summary="List recently processed webhooks",
        tags=["Webhooks"],
    )
    async def list_recent(self) -> JSONResponse:
        """Return recently processed webhooks from the cache."""
        recent = self._webhooks.get_recent(limit=20)
        return JSONResponse(
            status_code=200,
            content={"count": len(recent), "webhooks": recent},
        )
