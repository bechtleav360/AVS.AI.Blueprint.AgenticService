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

from blueprint.agents.agent import PromptLoader
from blueprint.agents.handler import EventHandler
from blueprint.agents.models import CloudEvent

from ..models import CustomPayload, HandlerResult, InvoiceAnalysisOutput

logger = logging.getLogger(__name__)


class AgentInvokerHandler(EventHandler):
    """Handler that validates input, invokes the AI agent, and publishes results.

    Returns HandlerResult with event_type to trigger automatic event publishing.
    Demonstrates three different event types based on validation status.
    """

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
    ) -> Optional[HandlerResult]:
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
            logger.error("Invalid payload format")
            return HandlerResult(
                data={"error": "Invalid payload format"},
                event_type="invoice.analysis.error",
                metadata={"reason": "invalid_payload"},
            )

        # Get pre-configured agent and process
        try:
            # Get agent from registry (configured at startup)
            agent = self._get_agent("invoice_analyzer")

            # Load instruction prompt from file with template variables
            instruction = PromptLoader.load_instruction_prompt(
                "instruction",
                self.__class__,
                config=None,  # Uses default search paths
                invoice_text=invoice_text,
                metadata=metadata,
            )

            # Run agent - expects InvoiceAnalysisOutput
            result = await agent.run(instruction)
            analysis: InvoiceAnalysisOutput = result.data

            logger.info(
                "Agent processing completed: status=%s, invoice_id=%s",
                analysis.status,
                analysis.invoice_id,
            )

            # Determine which event to publish based on validation status
            if analysis.status.lower() == "valid":
                event_type = "invoice.validated"
                logger.info("Invoice %s is VALID", analysis.invoice_id)
            elif analysis.status.lower() in ["invalid", "incomplete"]:
                event_type = "invoice.invalidated"
                logger.warning(
                    "Invoice %s is INVALID: %s", analysis.invoice_id, analysis.notes
                )
            else:
                # Unknown status - treat as invalid
                event_type = "invoice.invalidated"
                logger.warning(
                    "Invoice %s has unknown status: %s",
                    analysis.status,
                    analysis.invoice_id,
                )

            # Return structured result with event type for publishing
            return HandlerResult(
                data=analysis.model_dump(),
                event_type=event_type,
                metadata={
                    "invoice_id": analysis.invoice_id,
                    "status": analysis.status,
                    "confidence": analysis.confidence,
                },
            )

        except Exception as e:
            logger.error("Agent processing failed: %s", str(e), exc_info=True)
            # Return error result with error event type
            return HandlerResult(
                data={"error": str(e), "invoice_text_preview": invoice_text[:100]},
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
