"""Event models for the simple event processor."""

from pydantic import BaseModel, Field


class ProcessedResult(BaseModel):
    """Result of processing an event."""

    event_id: str = Field(..., description="Original event ID")
    status: str = Field(..., description="Processing status: 'success' or 'error'")
    message: str = Field(..., description="Processing result message")
    processed_data: dict = Field(default_factory=dict, description="Processed data")
    error: str | None = Field(None, description="Error message if processing failed")
