"""Event routing configuration models."""

from pydantic import BaseModel, Field


class EventRoutingConfig(BaseModel):
    """Configuration for routing a specific event type to a topic with optional routing key.

    This model defines how CloudEvents are routed to message broker topics
    with optional routing keys for advanced routing scenarios (e.g., RabbitMQ topic exchanges).
    """

    topic: str = Field(..., description="The topic/exchange to publish to")
    routing_key: str | None = Field(
        None,
        description="Optional routing key for topic-based routing (e.g., 'invoice.processed.success')",
    )

    class Config:
        """Pydantic configuration."""

        frozen = True  # Make immutable


class HandlerEventConfig(BaseModel):
    """Event configuration that handlers can define for success and error scenarios.

    Handlers use this to declare which event types they produce and how those
    events should be routed.
    """

    event_type: str = Field(..., description="CloudEvent type (e.g., 'agent.output.invoice.processed')")
    topic: str = Field(..., description="Topic/exchange to publish to")
    routing_key: str | None = Field(None, description="Optional routing key for advanced routing")

    class Config:
        """Pydantic configuration."""

        frozen = True
