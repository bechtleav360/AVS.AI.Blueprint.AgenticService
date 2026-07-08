"""Domain models for the sessions service integration."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobNotification(BaseModel):
    """A job dispatch notification received over the sessions SSE stream.

    Parsed once at the SSE boundary so field names and presence rules live in one
    place instead of being read ad hoc as ``dict`` keys throughout the bus. Extra
    keys in the payload are preserved (``extra="allow"``) and flow through to the
    CloudEvent ``data``.
    """

    model_config = ConfigDict(extra="allow")

    session_id: UUID
    job_id: UUID
    job_type: str
    created_at: str | None = None
    pipeline_id: str | None = None

    def payload(self) -> dict[str, Any]:
        """The full notification as a JSON-serialisable dict (UUIDs as strings)."""
        return self.model_dump(mode="json")
