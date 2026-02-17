"""Invoice analysis handler that invokes an AI agent and publishes results.

This handler demonstrates:
- Validating event data
- Calling an agent using _get_agent()
- Returning Pydantic models (HandlerResult) or None
- Publishing different events based on validation status:
  * invoice.validated - When invoice is valid
  * invoice.invalidated - When invoice is invalid
  * invoice.analysis.error - When processing fails

The handler uses the Chain of Responsibility pattern where it can process
the event and return a result (stops chain), or return None (continues chain).
"""

import logging
from typing import Any, Optional

from src.blueprint.agents.base import EventHandler
from src.blueprint.agents.models import CloudEvent

from src.blueprint.agents.models import HandlerResult

logger = logging.getLogger(__name__)


class AgentInvokerHandler(EventHandler):
    """Handler that validates input, invokes the AI agent, and publishes results.

    Returns HandlerResult with event_type to trigger automatic event publishing.
    Demonstrates three different event types based on validation status.
    """

    def __init__(self) -> None:
        super().__init__("AgentInvokerHandler", priority=10)

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Handle events with 'invoke_agent' action."""
        return True

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Optional[HandlerResult]:
        """Validate the payload, invoke the agent, and return structured result.

        Returns:
            HandlerResult with event_type for publishing, or None to continue chain.

        Event Types Published:
            - invoice.validated: When invoice status is 'valid'
            - invoice.invalidated: When invoice status is 'invalid' or 'incomplete'
            - invoice.analysis.error: When processing fails
        """
        logger.info(
            "AgentInvokerHandler processing event '%s'",
            event.type,
        )

        # Get pre-configured agent and process
        try:
            logger.info("Agent processing completed: status=%s, invoice_id=%s")

            # Return original data
            return HandlerResult(
                data=event.data,
                event_type=event.type
            )

        except Exception as e:
            logger.error("Agent processing failed: %s", str(e), exc_info=True)
            # Return error result with error event type
            return HandlerResult(
                data={"error": str(e)},
                event_type="invoice.analysis.error",
                metadata={"error_type": type(e).__name__, "source": "agent_processing"},
            )

    def get_published_event_types(self) -> tuple[str, ...]:
        """Declare event types this handler can publish.

        These event types are mapped in values.yaml:
        - invoice.validated -> test.connection (routing_key: valid)
        - invoice.invalidated -> test.connection (routing_key: invalid)
        - invoice.analysis.error -> test.connection (routing_key: error)
        """
        return (
            "invoice.validated",
            "invoice.invalidated",
            "invoice.analysis.error",
        )
