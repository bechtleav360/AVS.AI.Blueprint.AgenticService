"""Handler that enriches and publishes the final event (priority 15)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..services.webhook_service import WebhookService

logger = logging.getLogger(__name__)

# Simple priority scoring by event category keyword.
_PRIORITY_KEYWORDS: dict[str, int] = {
    "security": 90,
    "payment": 80,
    "deploy": 70,
    "release": 60,
    "push": 50,
    "pull_request": 40,
    "issue": 30,
}


def _score_priority(event_category: str) -> int:
    """Return a numeric priority score (higher = more important)."""
    lower = event_category.lower()
    for keyword, score in _PRIORITY_KEYWORDS.items():
        if keyword in lower:
            return score
    return 10  # default low priority


class MetadataEnricher(EventHandlerBase):
    """Add priority score and processed timestamp, then publish.

    This is the terminal handler in the chain. It always returns a
    ``HandlerResult`` with event_type ``webhook.processed``.
    """

    def __init__(self) -> None:
        super().__init__(priority=15)

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
        normalized = context.get("normalized_event", event.data)
        webhook_id = context.get("webhook_id", event.id)

        # Enrich
        enriched: dict[str, Any] = {**normalized}
        enriched["priority_score"] = _score_priority(
            normalized.get("event_category", "")
        )
        enriched["processed_at"] = datetime.now(UTC).isoformat()
        enriched["webhook_id"] = webhook_id

        # Mark as processed for dedup and store for the recent-list
        webhook_service.mark_processed(webhook_id)
        webhook_service.store_recent(webhook_id, enriched)

        logger.info(
            "Enriched webhook %s (priority=%s)", webhook_id, enriched["priority_score"]
        )

        return HandlerResult(
            event_type="webhook.processed",
            data=enriched,
        )

    def get_published_event_types(self) -> tuple[str, str] | None:
        return ("webhook.processed", "webhook.processed.error")
