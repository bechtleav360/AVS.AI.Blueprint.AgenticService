"""Business logic for webhook normalisation and deduplication."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.services.infrastructure.cache_service import CacheService

from ..models.schemas import NormalizedEvent, WebhookPayload

logger = logging.getLogger(__name__)

WEBHOOK_NAMESPACE = "webhooks"
RECENT_NAMESPACE = "webhooks_recent"


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
    # Normalisation
    # ------------------------------------------------------------------

    def normalize_payload(self, payload: WebhookPayload) -> NormalizedEvent:
        """Convert a source-specific webhook into a NormalizedEvent."""
        if payload.source == "github":
            return self._normalize_github(payload)
        if payload.source == "stripe":
            return self._normalize_stripe(payload)
        return self._normalize_generic(payload)

    @staticmethod
    def _normalize_github(payload: WebhookPayload) -> NormalizedEvent:
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
    def _normalize_stripe(payload: WebhookPayload) -> NormalizedEvent:
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
    def _normalize_generic(payload: WebhookPayload) -> NormalizedEvent:
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
        return self._cache.list_values(namespace=RECENT_NAMESPACE, limit=limit)  # type: ignore[return-value]
