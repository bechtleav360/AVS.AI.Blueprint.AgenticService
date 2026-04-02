"""Handler that filters out unwanted webhook events (priority 10)."""

from __future__ import annotations

import logging
from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

logger = logging.getLogger(__name__)


class ContentFilter(EventHandlerBase):
    """Drop bot-generated and test events.

    Filtering rules:
    - GitHub: actor containing ``[bot]`` is discarded.
    - Stripe: event_category starting with ``test_`` is discarded.

    When an event is filtered a ``webhook.filtered`` result is returned so it
    can be published to the filtered-events topic. If the event passes, the
    handler returns ``None`` to continue the chain.
    """

    def __init__(self) -> None:
        super().__init__(priority=10)

    async def on_startup(self) -> None:
        """No handler-specific startup needed."""

    async def on_shutdown(self) -> None:
        """No handler-specific shutdown needed."""

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "webhook.received"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        normalized = context.get("normalized_event", event.data)
        webhook_id = context.get("webhook_id", event.id)

        actor = normalized.get("actor") or ""
        event_category = normalized.get("event_category", "")
        original_source = normalized.get("original_source", "")

        # GitHub bot filter
        if original_source == "github" and "[bot]" in actor:
            reason = f"Filtered GitHub bot event from {actor}"
            logger.info(reason)
            return HandlerResult(
                event_type="webhook.filtered",
                data={"reason": reason, "webhook_id": webhook_id},
            )

        # Stripe test-event filter
        if original_source == "stripe" and event_category.startswith("test_"):
            reason = f"Filtered Stripe test event: {event_category}"
            logger.info(reason)
            return HandlerResult(
                event_type="webhook.filtered",
                data={"reason": reason, "webhook_id": webhook_id},
            )

        # Event is allowed -- pass to next handler
        return None

    def get_published_event_types(self) -> tuple[str, str] | None:
        return ("webhook.filtered", "webhook.filtered.error")
