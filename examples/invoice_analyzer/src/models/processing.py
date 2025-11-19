"""Processing context models for the custom agent."""

from uuid import UUID

from pydantic import BaseModel


class ProcessingContext(BaseModel):
    """
    Context for the agent's processing.

    Replace or extend this with your domain-specific context data, such as a
    resource model, user information, correlation identifiers, etc.
    """

    correlation_id: UUID | None = None
    event_id: UUID | None = None
