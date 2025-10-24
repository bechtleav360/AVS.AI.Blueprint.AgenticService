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

from base.src.agent import PromptLoader
from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import AssetHarmonizingOutput, HandlerResult
from pathlib import Path

logger = logging.getLogger(__name__)

THIS_FILE = Path(__file__).resolve()
BLUEPRINT_ROOT = THIS_FILE.parents[1]

class AgentInvokerHandler(EventHandler):
    """Handler that validates input, invokes the AI agent, and publishes results.

    Returns HandlerResult with event_type to trigger automatic event publishing.
    Demonstrates three different event types based on validation status.
    """

    def __init__(self) -> None:
        super().__init__("AgentInvokerHandler", priority=20)

    async def can_handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> bool:
        """Handle events"""
        if not event.data:
            return False

        return True

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

        asset = context.get("asset_fetched")

        if not asset or not isinstance(asset, dict):
            return HandlerResult(
                data={"error": "Invalid payload format"},
                event_type="invoice.analysis.error",
                metadata={"reason": "No asset in context to update tags"},
            )



        # Get pre-configured agent and process
        try:
            # Get agent from registry (configured at startup)
            agent = self._get_agent("asset_harmonizing")

            # Load instruction prompt from file with template variables
            instruction = PromptLoader.load_instruction_prompt(
                "asset_harmonizing",
                self.__class__,
                config=None,  # Uses default search paths
                asset=asset,
            )

            # Run agent - expects InvoiceAnalysisOutput
            result = await agent.run(instruction)
            clean_output = AssetHarmonizingOutput.model_validate_json(result.output)

            logger.info(
                "Agent processing completed: clean_outout=%s, ",
                clean_output
            )

            context["asset_tagged"] = clean_output
            # # Determine which event to publish based on validation status
            # if analysis.status.lower() == "valid":
            #     event_type = "invoice.validated"
            #     logger.info("Invoice %s is VALID", analysis.invoice_id)
            # elif analysis.status.lower() in ["invalid", "incomplete"]:
            #     event_type = "invoice.invalidated"
            #     logger.warning(
            #         "Invoice %s is INVALID: %s", analysis.invoice_id, analysis.notes
            #     )
            # else:
            #     # Unknown status - treat as invalid
            #     event_type = "invoice.invalidated"
            #     logger.warning(
            #         "Invoice %s has unknown status: %s",
            #         analysis.status,
            #         analysis.invoice_id,
            #     )

            # # Return structured result with event type for publishing
            # return HandlerResult(
            #     data=analysis.model_dump(),
            #     event_type=event_type,
            #     metadata={
            #         "invoice_id": analysis.invoice_id,
            #         "status": analysis.status,
            #         "confidence": analysis.confidence,
            #     },
            # )
            return None

        except Exception as e:
            logger.error("Agent processing failed: %s", str(e), exc_info=True)
            # Return error result with error event type
            return HandlerResult(
                data={"error": str(e), "asset": asset},
                event_type="invoice.analysis.error",
                metadata={"error_type": type(e).__name__, "source": "agent_processing"},
            )

    def get_published_event_types(self) -> tuple[str, ...]:

        return ()
