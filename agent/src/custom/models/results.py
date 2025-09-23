"""Custom result models for the agent outputs."""

from typing import Optional, Dict, Any

from base.src.models.domain import AgentOutput


class CustomAgentOutput(AgentOutput):
    """Domain-specific agent output extending the base `AgentOutput`.

    Add additional, typed fields that your application expects from the agent.
    """

    confidence: Optional[float] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
