"""Custom result models for the agent outputs."""

from typing import Any

from base.src.models.result import AgentOutput


class CustomAgentOutput(AgentOutput):
    """Domain-specific agent output extending the base `AgentOutput`.

    Add additional, typed fields that your application expects from the agent.
    """

    confidence: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
