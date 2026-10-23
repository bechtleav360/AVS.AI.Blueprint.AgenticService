"""Domain models: what the service works with. No CloudEvent and no DTO reaches the service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IncomingWebhook(BaseModel):
    """One webhook to relay, identified by ``webhook_id``."""

    webhook_id: str
    source: str
    event_type: str
    payload: dict[str, Any]


class NormalizedEvent(BaseModel):
    """Source-agnostic representation of a webhook event."""

    original_source: str
    event_category: str
    event_action: str
    actor: str | None = None
    resource_id: str | None = None
    resource_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )


class RelayOutcome(BaseModel):
    """What the service decided for one webhook.

    ``duplicate``: already relayed, nothing to do. ``filtered``: dropped by a content rule, ``data``
    says why. ``processed``: normalised and enriched, ``data`` is the event to publish.
    """

    kind: Literal["duplicate", "filtered", "processed"]
    reason: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
