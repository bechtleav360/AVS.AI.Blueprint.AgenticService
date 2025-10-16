"""Example handler that invokes an AI agent for processing.

This handler demonstrates:
- Validating event data
- Calling an agent runtime directly using _get_agent_runtime()
- Returning a final result (stops the chain)
- Error handling for agent failures

The handler uses the Chain of Responsibility pattern where it can process
the event and return a result, or return None to pass to the next handler.
"""

import logging
from typing import Any, Optional

from base.src.agent import PromptLoader
from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import CustomPayload

# from ..models.domain import AgentOutput

logger = logging.getLogger(__name__)


class AgentInvokerHandler(EventHandler):
    """Handler that validates input and invokes the Pydantic AI agent."""

    def __init__(self) -> None:
        super().__init__("AgentInvokerHandler", priority=10)

    async def can_handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> bool:
        """Handle events with 'invoke_agent' action."""
        if not event.data:
            return False

        # Handle both CustomPayload objects and plain dictionaries
        if isinstance(event.data, CustomPayload):
            return event.data.details.get("action") == "invoke_agent"
        elif isinstance(event.data, dict):
            details = event.data.get("details", {})
            return details.get("action") == "invoke_agent"

        return False

    async def handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Any | None:
        """Validate the payload and invoke the agent."""
        logger.info(
            "AgentInvokerHandler processing event '%s'",
            event.type,
        )

        # Extract payload
        payload = event.data

        # Handle both CustomPayload objects and plain dictionaries
        if isinstance(payload, CustomPayload):
            invoice_text = payload.invoice_text
            metadata = payload.details
        elif isinstance(payload, dict):
            invoice_text = payload.get("invoice_text")
            metadata = payload.get("details", {})
        else:
            return {"status": "error", "message": "Invalid payload format"}

        # Get pre-configured agent and process
        try:
            # Get agent from registry (configured at startup)
            agent = self._get_agent("invoice_analyzer")

            # Load instruction prompt from file with template variables
            # The prompt file path can be overridden via environment config
            instruction = PromptLoader.load_instruction_prompt(
                "instruction",
                self.__class__,
                config=None,  # Uses default search paths
                invoice_text=invoice_text,
                metadata=metadata,
            )

            # Run agent
            result = await agent.run(instruction)

            logger.info("Agent processing completed successfully")

            return {
                "status": "success",
                "result": result.data,
            }

        except Exception as e:
            logger.error("Agent processing failed: %s", str(e), exc_info=True)
            return {
                "status": "error",
                "message": str(e),
            }

    def get_published_event_types(self):
        """Declare event types this handler publishes."""
        return (
            "agent.output.invoice.processed",
            "agent.error.invoice.processing",
        )
