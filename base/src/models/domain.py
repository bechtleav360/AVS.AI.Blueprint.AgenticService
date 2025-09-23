"""
Domain-specific models for the agent.

FIXME: This file should contain the Pydantic models that are specific to your
domain, such as the resource model and the agent's output model.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ResourceMetadata(BaseModel):
    """
    Represents the metadata of a resource to be processed by the agent.

    FIXME: Replace this with your domain-specific resource model. Add fields
    that are relevant to your use case, such as `tags`, `owner`, `region`, etc.
    """
    id: str = Field(..., description="Unique identifier for the resource.")
    name: str = Field(..., description="Human-readable name of the resource.")
    type: str = Field(..., description="The type of the resource (e.g., 'vm', 'database').")
    environment: Optional[str] = Field(None, description="The environment the resource belongs to (e.g., 'prod', 'dev').")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional properties of the resource."
    )


class AgentOutput(BaseModel):
    """
    Represents the output of the agent's processing.

    FIXME: Customize this model to represent the structured output of your agent.
    This could include fields like `status`, `risk_level`, `findings`, etc.
    """
    resource_id: str = Field(..., description="The ID of the resource that was processed.")
    status: str = Field(..., description="The final status of the processing (e.g., 'compliant', 'vulnerable').")
    confidence: float = Field(..., description="The confidence score of the analysis (0.0 to 1.0).")
    evidence: List[str] = Field(
        default_factory=list, description="A list of evidence supporting the analysis."
    )
    recommendations: List[str] = Field(
        default_factory=list, description="A list of actionable recommendations."
    )
    error: Optional[str] = Field(None, description="Any error that occurred during processing.")
    correlation_id: Optional[UUID] = Field(None, description="The correlation ID for tracing.")
