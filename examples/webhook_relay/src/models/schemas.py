"""DTOs: what arrives over HTTP and in the ``webhook.received`` event."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class WebhookPayload(BaseModel):
    """Incoming webhook payload from an external source (REST body and event data)."""

    source: Literal["github", "stripe", "generic"] = "generic"
    event_type: str
    payload: dict[str, Any]
    timestamp: str | None = None
    webhook_id: str | None = None
