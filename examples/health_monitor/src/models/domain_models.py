"""Pydantic models for the Health Monitor."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EndpointConfig(BaseModel):
    """Configuration for a single monitored endpoint."""

    name: str
    url: str
    interval_seconds: int = 60


class HealthResult(BaseModel):
    """Result of a single health check against an endpoint."""

    endpoint_name: str
    url: str
    status_code: int | None = None
    response_time_ms: float | None = None
    healthy: bool
    error: str | None = None
    checked_at: str


class EndpointStatus(BaseModel):
    """Aggregated status for a monitored endpoint."""

    endpoint_name: str
    url: str
    current_health: HealthResult | None = None
    uptime_percentage: float = 0.0
    total_checks: int = 0
    consecutive_failures: int = 0
    last_healthy: str | None = None


class UptimeReport(BaseModel):
    """Full uptime report across all monitored endpoints."""

    generated_at: str
    endpoints: list[EndpointStatus] = Field(default_factory=list)
    overall_healthy: bool = True
