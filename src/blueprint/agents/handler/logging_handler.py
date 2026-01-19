"""Logging handler for debugging and monitoring event flow.

This handler prints event content to the console for debugging purposes.
It can be used in any agent to inspect incoming events.
"""

import json
import logging
from typing import Any

from ..base import EventHandler
from ..models.events import GenericCloudEvent

logger = logging.getLogger(__name__)


class LoggingHandler(EventHandler):
    """
    Handler that logs event content to console.

    This handler is useful for:
    - Debugging event flow
    - Monitoring incoming events
    - Understanding event structure
    - Development and testing

    Usage:
        ```python
        logging_handler = LoggingHandler(priority=10)  # Run first
        chain.add_handler(logging_handler)
        ```
    """

    def __init__(self, priority: int = 10, log_level: str = "INFO"):
        """
        Initialize the logging handler.

        Args:
            priority: Execution priority (lower runs first, default: 10)
            log_level: Log level for event output (DEBUG, INFO, WARNING, ERROR)
        """
        super().__init__("LoggingHandler", priority=priority)
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        """Always returns True - this handler processes all events."""
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> Any | None:
        """
        Log event content to console.

        Args:
            event: The CloudEvent to log
            context: Processing context

        Returns:
            None (this handler doesn't modify the event)
        """
        separator = "=" * 70
        logger.log(self.log_level, separator)
        logger.log(self.log_level, "📨 EVENT RECEIVED")
        logger.log(self.log_level, separator)

        # Log event metadata
        logger.log(self.log_level, "")
        logger.log(self.log_level, "📋 CloudEvent Metadata:")
        logger.log(self.log_level, "   Spec Version: %s", event.specversion)
        logger.log(self.log_level, "   Event ID: %s", event.id)
        logger.log(self.log_level, "   Type: %s", event.type)
        logger.log(self.log_level, "   Source: %s", event.source)

        if event.subject:
            logger.log(self.log_level, "   Subject: %s", event.subject)

        if event.time:
            logger.log(self.log_level, "   Time: %s", event.time.isoformat())

        if event.datacontenttype:
            logger.log(self.log_level, "   Content Type: %s", event.datacontenttype)

        # Log event data
        logger.log(self.log_level, "")
        logger.log(self.log_level, "📦 Event Data:")

        if event.data:
            try:
                # Pretty print JSON data
                data_str = json.dumps(event.data, indent=3, default=str)
                logger.log(self.log_level, "%s", data_str)
            except (TypeError, ValueError):
                # Fallback for non-JSON serializable data
                logger.log(self.log_level, "%s", str(event.data))
        elif event.data_base64:
            logger.log(self.log_level, "   [Base64 encoded data]")
            logger.log(self.log_level, "   %s", event.data_base64[:100] + "...")
        else:
            logger.log(self.log_level, "   [No data]")

        # Log context
        if context:
            logger.log(self.log_level, "")
            logger.log(self.log_level, "🔧 Processing Context:")
            for key, value in context.items():
                logger.log(self.log_level, "   %s: %s", key, value)

        logger.log(self.log_level, "")
        logger.log(self.log_level, separator)

        # Return None to pass event to next handler
        return None
