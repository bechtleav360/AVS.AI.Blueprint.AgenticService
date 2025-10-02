"""Custom tools for the Pydantic AI agent (generic example)."""

import logging
from uuid import UUID

from pydantic_ai import RunContext

from ..models import CustomAgentOutput, ProcessingContext, ResourceInput
from .logic import ProcessingLogic

logger = logging.getLogger(__name__)


class MyTool(Tool):
    """My tool."""

    async def run(self, ctx: RunContext[ProcessingContext], resource: ResourceInput) -> CustomAgentOutput:
        """
        Analyze a resource deterministically and return a structured result the
        agent can use directly or map into its final output.

        Returns a dictionary shaped to align with `CustomAgentOutput` fields to
        make it easy for the model to adopt as the final output when appropriate.
        """
        logger.info("Executing analyze_resource tool.")


class Tools:
    """
    Encapsulates deterministic business logic that the agent can invoke as tools.

    This keeps core rules testable and efficient while allowing the LLM to
    orchestrate and explain results.
    """

    async def analyze_resource(self, ctx: RunContext[ProcessingContext], resource: ResourceInput) -> CustomAgentOutput:
        """
        Analyze a resource deterministically and return a structured result the
        agent can use directly or map into its final output.

        Returns a dictionary shaped to align with `CustomAgentOutput` fields to
        make it easy for the model to adopt as the final output when appropriate.
        """
        logger.info("Executing analyze_resource tool.")

        resource_dict = resource.model_dump()
        analysis = ProcessingLogic.analyze_resource(resource_dict)
        recommendations = ProcessingLogic.generate_recommendations(analysis, resource_dict)

        return CustomAgentOutput(
            resource_id=resource.id or "unknown",
            status=analysis.get("status"),
            confidence=analysis.get("confidence"),
            evidence=[],  # TODO: Convert analysis evidence to Evidence objects
            recommendations=recommendations,
            reasoning="Analysis performed by ProcessingLogic",
            correlation_id=(UUID(ctx.deps.correlation_id) if ctx.deps and ctx.deps.correlation_id else None),
            event_id=(UUID(ctx.deps.event_id) if ctx.deps and ctx.deps.event_id else None),
            metadata={
                "classification": analysis.get("classification"),
                "evidence": analysis.get("evidence", []),
                "context": {
                    "correlation_id": (str(ctx.deps.correlation_id) if ctx.deps and ctx.deps.correlation_id else None),
                    "event_id": (str(ctx.deps.event_id) if ctx.deps and ctx.deps.event_id else None),
                },
            },
        )
