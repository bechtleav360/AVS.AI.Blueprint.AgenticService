"""The handler for ``webhook.received``: translate the event, call the service once, translate back."""

from __future__ import annotations

from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..models.domain import IncomingWebhook
from ..models.schemas import WebhookPayload
from ..services.webhook_service import WebhookService

WEBHOOK_RECEIVED = "webhook.received"


class WebhookHandler(EventHandlerBase):
    """Relays incoming webhooks. All decisions -- duplicate, filtered, enriched -- are the service's."""

    def __init__(self) -> None:
        super().__init__(priority=10)

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(WebhookService)

    async def on_shutdown(self) -> None:
        """No handler-specific shutdown needed."""

    def get_handled_event_types(self) -> list[str]:
        return [WEBHOOK_RECEIVED]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == WEBHOOK_RECEIVED

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
        payload = self.extract_payload(event, WebhookPayload)
        webhook = IncomingWebhook(
            webhook_id=payload.webhook_id or event.id,
            source=payload.source,
            event_type=payload.event_type,
            payload=payload.payload,
        )
        outcome = await self._service.relay(webhook)
        if outcome.kind == "duplicate":
            return HandlerResult.skipped(outcome.reason)
        if outcome.kind == "filtered":
            return HandlerResult(event_type="webhook.filtered", data=outcome.data)
        return HandlerResult(event_type="webhook.processed", data=outcome.data)

    def get_published_event_types(self) -> tuple[str, str] | None:
        return ("webhook.processed", "webhook.filtered")
