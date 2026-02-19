"""Pydantic models for the scheduler example."""

from datetime import datetime

from pydantic import BaseModel, Field


class MetricSnapshot(BaseModel):
    """A single recorded metric snapshot."""

    timestamp: datetime = Field(description="When the metric was recorded")
    value: float = Field(description="The metric value")
    label: str = Field(description="Metric label / source")


class MetricSummary(BaseModel):
    """Aggregated summary of recorded metrics."""

    label: str = Field(description="Metric label")
    count: int = Field(description="Number of snapshots recorded")
    average: float = Field(description="Average value across all snapshots")
    minimum: float = Field(description="Minimum value recorded")
    maximum: float = Field(description="Maximum value recorded")
    last_recorded: datetime | None = Field(None, description="Timestamp of the most recent snapshot")
