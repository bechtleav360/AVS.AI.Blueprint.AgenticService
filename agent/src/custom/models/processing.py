"""Processing context models for the custom agent."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ProcessingContext(BaseModel):
    """
    Context for the agent's processing.

    Replace or extend this with your domain-specific context data, such as a
    resource model, user information, correlation identifiers, etc.
    """

    correlation_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
