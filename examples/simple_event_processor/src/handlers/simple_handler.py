"""Simple event processor handler."""

import logging
from typing import Any

from blueprint.agents.base import EventHandler
from blueprint.agents.models.events import CloudEvent

from ..models.events import ProcessedResult

logger = logging.getLogger(__name__)


class SimpleProcessorHandler(EventHandler):
    """Simple event processor handler that processes events without AI."""

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Check if this handler can process the event.

        Handles events of type 'data.received'.

        Args:
            event: The cloud event to check
            context: Processing context

        Returns:
            True if this handler can process the event
        """
        return event.type == "data.received"

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> ProcessedResult:
        """Process the event.

        Args:
            event: The cloud event to process
            context: Processing context

        Returns:
            ProcessedResult with processing status and data
        """
        try:
            logger.info(f"Processing event: {event.id} from {event.source}")

            # Simple processing: echo back the data with metadata
            event_data = event.data or {}
            processed_data = {
                "original_data": event_data,
                "processed_at": event.time,
                "source": event.source,
                "item_count": len(event_data) if isinstance(event_data, dict) else 0,
            }

            result = ProcessedResult(
                event_id=event.id,
                status="success",
                message=f"Successfully processed event from {event.source}",
                processed_data=processed_data,
            )

            logger.info(f"Event {event.id} processed successfully")
            return result

        except Exception as e:
            logger.error(f"Error processing event: {str(e)}", exc_info=True)
            return ProcessedResult(
                event_id=event.id,
                status="error",
                message="Failed to process event",
                error=str(e),
            )
