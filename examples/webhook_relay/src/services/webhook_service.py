"""Business logic of the relay: deduplication, normalisation, content filtering and enrichment."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.services.infrastructure.cache_service import CacheService

from ..models.domain_models import IncomingWebhook, NormalizedEvent, RelayOutcome

logger = logging.getLogger(__name__)

WEBHOOK_NAMESPACE = "webhooks"
RECENT_NAMESPACE = "webhooks_recent"

# Simple priority scoring by event category keyword (higher = more important).
_PRIORITY_KEYWORDS: dict[str, int] = {
    "security": 90,
    "payment": 80,
    "deploy": 70,
    "release": 60,
    "push": 50,
    "pull_request": 40,
    "issue": 30,
}


class WebhookService(ServiceBase):
    """Normalizes webhook payloads and tracks duplicates via the cache."""

    def __init__(self) -> None:
        super().__init__()
        self._cache: CacheService | None = None

    async def on_startup(self) -> None:
        """Acquire the cache service from the registry."""
        if self.registry.has_cache():
            self._cache = self.registry.cache_service
            logger.info("WebhookService connected to cache service")
        else:
            logger.warning("No cache service available; deduplication disabled")

    async def on_shutdown(self) -> None:
        """Nothing to tear down."""

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def relay(self, webhook: IncomingWebhook) -> RelayOutcome:
        """Decide what happens to one webhook: the one method the handler calls.

        Duplicate -> nothing to do. A content rule matches -> filtered, with the reason. Otherwise
        normalised, enriched, recorded for deduplication and the recent list, and returned for
        publishing.
        """
        if self.is_duplicate(webhook.webhook_id):
            return RelayOutcome(kind="duplicate", reason=f"webhook {webhook.webhook_id} already relayed")
        normalized = self.normalize_payload(webhook)
        reason = self.filter_reason(normalized)
        if reason is not None:
            logger.info("Webhook %s filtered: %s", webhook.webhook_id, reason)
            return RelayOutcome(kind="filtered", reason=reason, data={"reason": reason, "webhook_id": webhook.webhook_id})
        enriched = self.enrich(normalized, webhook.webhook_id)
        self.mark_processed(webhook.webhook_id)
        self.store_recent(webhook.webhook_id, enriched)
        logger.info("Relayed webhook %s (priority=%s)", webhook.webhook_id, enriched["priority_score"])
        return RelayOutcome(kind="processed", data=enriched)

    # ------------------------------------------------------------------
    # Filtering and enrichment
    # ------------------------------------------------------------------

    @staticmethod
    def filter_reason(normalized: NormalizedEvent) -> str | None:
        """Why this event is dropped, or ``None`` to relay it.

        GitHub: an actor containing ``[bot]``. Stripe: an event category starting with ``test_``.
        """
        actor = normalized.actor or ""
        if normalized.original_source == "github" and "[bot]" in actor:
            return f"Filtered GitHub bot event from {actor}"
        if normalized.original_source == "stripe" and normalized.event_category.startswith("test_"):
            return f"Filtered Stripe test event: {normalized.event_category}"
        return None

    @staticmethod
    def score_priority(event_category: str) -> int:
        """Return a numeric priority score (higher = more important)."""
        lower = event_category.lower()
        for keyword, score in _PRIORITY_KEYWORDS.items():
            if keyword in lower:
                return score
        return 10

    def enrich(self, normalized: NormalizedEvent, webhook_id: str) -> dict[str, Any]:
        """The event to publish: the normalised fields plus priority score, timestamp and id."""
        enriched: dict[str, Any] = normalized.model_dump()
        enriched["priority_score"] = self.score_priority(normalized.event_category)
        enriched["processed_at"] = datetime.now(UTC).isoformat()
        enriched["webhook_id"] = webhook_id
        return enriched

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def normalize_payload(self, payload: IncomingWebhook) -> NormalizedEvent:
        """Convert a source-specific webhook into a NormalizedEvent."""
        if payload.source == "github":
            return self._normalize_github(payload)
        if payload.source == "stripe":
            return self._normalize_stripe(payload)
        return self._normalize_generic(payload)

    @staticmethod
    def _normalize_github(payload: IncomingWebhook) -> NormalizedEvent:
        data = payload.payload
        action = data.get("action", payload.event_type)
        sender = data.get("sender", {})
        repo = data.get("repository", {})

        return NormalizedEvent(
            original_source="github",
            event_category=payload.event_type,
            event_action=action,
            actor=sender.get("login"),
            resource_id=repo.get("full_name"),
            resource_type="repository",
            metadata={
                "delivery_id": payload.webhook_id,
                "raw_event_type": payload.event_type,
            },
        )

    @staticmethod
    def _normalize_stripe(payload: IncomingWebhook) -> NormalizedEvent:
        data = payload.payload
        event_type_parts = data.get("type", payload.event_type).rsplit(".", 1)
        category = event_type_parts[0] if len(event_type_parts) > 1 else payload.event_type
        action = event_type_parts[-1] if len(event_type_parts) > 1 else "unknown"

        return NormalizedEvent(
            original_source="stripe",
            event_category=category,
            event_action=action,
            actor=None,
            resource_id=data.get("id"),
            resource_type=data.get("object"),
            metadata={
                "stripe_event_type": data.get("type", payload.event_type),
            },
        )

    @staticmethod
    def _normalize_generic(payload: IncomingWebhook) -> NormalizedEvent:
        return NormalizedEvent(
            original_source=payload.source,
            event_category=payload.event_type,
            event_action=payload.event_type,
            actor=payload.payload.get("actor"),
            resource_id=payload.payload.get("resource_id"),
            resource_type=payload.payload.get("resource_type"),
            metadata=payload.payload,
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def is_duplicate(self, webhook_id: str) -> bool:
        """Return True if *webhook_id* was already processed."""
        if self._cache is None:
            return False
        return self._cache.exists(webhook_id, namespace=WEBHOOK_NAMESPACE)

    def mark_processed(self, webhook_id: str) -> None:
        """Record *webhook_id* in the cache to prevent reprocessing."""
        if self._cache is None:
            return
        self._cache.set(
            webhook_id,
            {"processed_at": datetime.now(UTC).isoformat()},
            namespace=WEBHOOK_NAMESPACE,
            ttl=3600,
        )

    # ------------------------------------------------------------------
    # Recent-event tracking (for the REST query endpoint)
    # ------------------------------------------------------------------

    def store_recent(self, webhook_id: str, data: dict[str, Any]) -> None:
        """Keep a copy of the enriched event for the /webhooks/recent endpoint."""
        if self._cache is None:
            return
        self._cache.set(webhook_id, data, namespace=RECENT_NAMESPACE, ttl=3600)

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recently stored webhook summaries."""
        if self._cache is None:
            return []
        return list(self._cache.list_values(namespace=RECENT_NAMESPACE, limit=limit))
