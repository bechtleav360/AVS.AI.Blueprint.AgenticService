"""Pydantic models for the webhook relay pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    """Incoming webhook payload from an external source."""

    source: Literal["github", "stripe", "generic"] = "generic"
    event_type: str
    payload: dict[str, Any]
    timestamp: str | None = None
    webhook_id: str | None = None


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


class FilterDecision(BaseModel):
    """Result of the content-filtering stage."""

    allowed: bool
    reason: str
