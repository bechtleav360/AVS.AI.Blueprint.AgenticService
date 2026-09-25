"""Generic result models for agent processing outcomes."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .events import HandlerResult


class Evidence(BaseModel):
    """A piece of evidence supporting a conclusion."""

    type: str = Field(..., description="Type of evidence (e.g., 'tag', 'api_response').")
    source: str = Field(..., description="The source of the evidence.")
    value: Any = Field(..., description="The actual evidence content.")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for this piece of evidence (0.0-1.0).",
    )
    description: str | None = Field(None, description="A human-readable description of the evidence.")


class AgentOutput(BaseModel):
    """A generic, structured output from an agent's analysis."""

    resource_id: str = Field(..., description="The unique identifier of the resource that was analyzed.")
    status: str = Field(
        ...,
        description="The final determined status of the resource (e.g., 'compliant', 'vulnerable').",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="The overall confidence in the status determination.",
    )

    evidence: list[Evidence] = Field(
        default_factory=list,
        description="A list of evidence supporting the conclusion.",
    )
    reasoning: str | None = Field(None, description="The reasoning process or explanation from the AI agent.")
    recommendations: list[str] = Field(default_factory=list, description="Actionable recommendations for the user.")
    risk_level: str | None = Field(None, description="An assessed risk level (e.g., 'low', 'medium', 'high').")

    processed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="The timestamp of when the analysis was performed.",
    )
    agent_version: str | None = Field(None, description="The version of the agent that performed the analysis.")
    processing_time_ms: int | None = Field(None, description="The total processing time in milliseconds.")

    correlation_id: UUID | None = Field(None, description="A correlation ID for tracing the request through systems.")
    event_id: UUID | None = Field(None, description="The ID of the event that may have triggered this analysis.")

    @field_validator("evidence")
    @classmethod
    def sort_evidence_by_confidence(cls, v: list[Evidence]) -> list[Evidence]:
        """Sorts evidence by confidence in descending order for easier processing."""
        if v:
            return sorted(v, key=lambda e: e.confidence, reverse=True)
        return v


class ProcessingStatus(StrEnum):
    """Enumeration of processing outcomes."""

    PROCESSED = "processed"
    NO_HANDLER_FOUND = "no_handler_found"


class ProcessingResult(BaseModel):
    """Structured result emitted by the processing service."""

    request_id: str = Field(..., description="Unique identifier for the processing request.")
    status: ProcessingStatus = Field(..., description="Processing status (e.g., 'processed', 'no_handler_found').")
    result: list[HandlerResult] = Field(default_factory=list, description="Handler results produced during processing.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata about the processing run.")
    message: str | None = Field(None, description="Optional explanatory message for the processing outcome.")
