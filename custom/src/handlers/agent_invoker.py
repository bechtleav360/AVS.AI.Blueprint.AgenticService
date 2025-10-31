"""Asset harmonization handler that invokes the harmonizing agent and stores results.

This handler demonstrates:
- Validating event data
- Calling an agent using _get_agent()
- Producing a structured model result added to the processing context
- Deferring publication to a downstream publisher handler

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
import json
logger = logging.getLogger(__name__)

THIS_FILE = Path(__file__).resolve()
BLUEPRINT_ROOT = THIS_FILE.parents[1]

class AgentInvokerHandler(EventHandler):
    """Validate input, invoke harmonizing agent, and place results into context.

    Publication is handled by a dedicated publisher which reads context entries.
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
        """Validate the payload, invoke the harmonizing agent, and update context.

        Returns:
            None to continue the chain (publisher will read from context), or a
            HandlerResult with an error event type on failure.
        """
        logger.info(
            "AgentInvokerHandler processing event '%s'",
            event.type,
        )

        asset = context.get("asset_fetched")

        if not asset or not isinstance(asset, dict):
            logger.error(f"Asset has wrong format: {asset}")
            logger.error(f"Type is {type(asset)}")
            logger.error(f"Trying to convert to dict")
            try:
                asset = json.loads(asset)
            except Exception as e:
                logger.error(f"Failed to convert to dict: {e}")
                return HandlerResult(
                    data={"error": "Invalid payload format"},
                    event_type="asset.harmonization.error",
                    metadata={"reason": f"Asset has wrong format: {asset}"},
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

            # Run agent - expects AssetHarmonizingOutput
            result = await agent.run(instruction)
            clean_output = AssetHarmonizingOutput.model_validate_json(result.output)

            logger.info("Agent processing completed: clean_output=%s", clean_output)

            # Store harmonization result and status for downstream publisher
            context["asset_harmonized"] = clean_output
            #TODO: add error handling with other status values (should we use status for that?)
            context["harmonization_status"] = "valid"

            return None

        except Exception as e:
            logger.error("Agent processing failed: %s", str(e), exc_info=True)
            # Return error result with error event type
            return HandlerResult(
                data={"error": str(e), "asset": asset},
                event_type="asset.harmonization.error",
                metadata={"error_type": type(e).__name__, "source": "agent_processing"},
            )

    def get_published_event_types(self) -> tuple[str, ...]:

        return ()
