"""Handler that normalizes raw webhook payloads (priority 5 -- runs first)."""

from __future__ import annotations

import logging
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..models.schemas import WebhookPayload
from ..services.webhook_service import WebhookService

logger = logging.getLogger(__name__)


class WebhookNormalizer(EventHandlerBase):
    """Parse the incoming webhook, deduplicate, and normalize.

    Stores the normalized event in ``context["normalized_event"]`` so
    downstream handlers can use it without re-parsing.

    Returns ``None`` to pass control to the next handler.
    """

    def __init__(self) -> None:
        super().__init__(priority=5)

    async def on_startup(self) -> None:
        """No handler-specific startup needed."""

    async def on_shutdown(self) -> None:
        """No handler-specific shutdown needed."""

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> bool:
        return event.type == "webhook.received"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult | None:
        webhook_service: WebhookService = self.registry.get_service(WebhookService) # type: ignore

        # Parse incoming data into the domain model
        payload = WebhookPayload.model_validate(event.data)

        # Deduplicate
        webhook_id = payload.webhook_id or event.id
        if webhook_service.is_duplicate(webhook_id):
            logger.info("Duplicate webhook %s -- skipping", webhook_id)
            return None

        # Normalize
        normalized = webhook_service.normalize_payload(payload)
        context["normalized_event"] = normalized.model_dump()
        context["webhook_id"] = webhook_id
        logger.info(
            "Normalized webhook %s from %s (%s/%s)",
            webhook_id,
            normalized.original_source,
            normalized.event_category,
            normalized.event_action,
        )

        # Pass to next handler
        return None
