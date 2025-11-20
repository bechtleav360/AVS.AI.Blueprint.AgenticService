"""Generic result models for agent processing outcomes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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


class AnalysisRequest(BaseModel):
    """A generic request to analyze a resource."""

    resource_id: str | None = Field(None, description="The ID of a resource to fetch and analyze.")
    resource: dict[str, Any] | None = Field(None, description="The full resource data to analyze directly.")

    force_recheck: bool = Field(
        default=False,
        description="If true, forces a re-analysis even if a cached result exists.",
    )

    @model_validator(mode="before")
    @classmethod
    def check_resource_or_id_provided(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Ensures that either a resource or its ID is provided, but not both."""
        if not values.get("resource_id") and not values.get("resource"):
            raise ValueError("Either 'resource_id' or 'resource' must be provided.")
        if values.get("resource_id") and values.get("resource"):
            raise ValueError("Provide either 'resource_id' or 'resource', not both.")
        return values


class AnalysisResponse(BaseModel):
    """A generic response containing the result of an analysis."""

    success: bool = Field(..., description="Indicates whether the analysis was successfully completed.")
    result: AgentOutput | None = Field(None, description="The output of the analysis if successful.")
    error: str | None = Field(None, description="An error message if the analysis failed.")
