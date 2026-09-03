"""Domain models for the sessions service integration."""

from typing import Any, NotRequired, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobError(TypedDict):
    """Structured failure detail for a job, mirroring the svc-sessions ``/fail`` body.

    Matches service-sessions' ``JobError`` DTO: ``message`` required, ``code`` optional.
    Used as the payload for :meth:`SessionsApiClient.fail_job` and as the return shape of
    the :meth:`SessionsJobHandler.failure_of` extension point, so a key typo is caught by
    mypy at the construction site rather than at runtime against the live endpoint.
    """

    message: str
    code: NotRequired[str | None]


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
