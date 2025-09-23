"""Customizable event handlers for the decision engine.

Guide: How to add a custom handler
----------------------------------

This module is where you implement domain-specific event handlers that plug
into the framework's chain-of-responsibility `DecisionEngine`.

Key points:
- The base framework provides tracing automatically. You do NOT need to add
  spans in your handlers. Just implement business logic.
- Extend `base.src.agent.base.decisions.EventHandler` and override the two
  template methods:
  - `_can_handle(event, context) -> bool`: Return True if your handler should
    process the event.
  - `_handle(event, context) -> Optional[Any]`: Perform processing and return
    a result or `None` to pass control to the next handler.
- Register your handler in `get_all_handlers()` at the bottom of this file to
  enable the engine to use it.

Example:

```python
from base.src.agent.base.decisions import EventHandler
from base.src.models.events import CloudEvent

class MyHandler(EventHandler):
    def __init__(self):
        super().__init__("MyHandler", priority=20)

    async def _can_handle(self, event: CloudEvent, context: dict) -> bool:
        return event.type == "my.event.type"

    async def _handle(self, event: CloudEvent, context: dict):
        # domain logic here
        context["processed_by"] = self.name
        return {"status": "processed"}

# Add MyHandler() to get_all_handlers() below
```

Best practices:
- Keep handlers single-purpose and composable.
- Use `context` to pass data between handlers; avoid tight coupling.
- Prefer adding fields to custom models in `agent/src/custom/models/` and
  import them here if needed.
"""

import logging
from typing import Any, Dict, Optional, List

from base.src.models.events import CloudEvent
from base.src.agent.base.decisions import EventHandler

# FIXME: Import your domain-specific models.
# from ..models.domain import AgentOutput

logger = logging.getLogger(__name__)


class ValidationHandler(EventHandler):
    """Example handler for validating incoming events."""

    def __init__(self):
        super().__init__("ValidationHandler", priority=10)

    async def _can_handle(self, event: CloudEvent, context: Dict[str, Any]) -> bool:
        """This handler runs for all events to perform initial validation."""
        return True

    async def _handle(self, event: CloudEvent, context: Dict[str, Any]) -> Optional[Any]:
        """Perform validation checks on the event."""
        if not event.data:
            logger.warning("Event data is missing.")
            # FIXME: Return a proper error response.
            return {"status": "validation_failed", "reason": "Missing data"}

        logger.info("Event passed validation.")
        context["validated_at"] = "timestamp_placeholder"
        return None  # Pass to the next handler



class ProcessingHandler(EventHandler):
    """Example handler for the main business logic."""

    def __init__(self):
        super().__init__("ProcessingHandler", priority=30)

    async def _can_handle(self, event: CloudEvent, context: Dict[str, Any]) -> bool:
        """This handler runs for all validated events."""
        return "validated_at" in context

    async def _handle(self, event: CloudEvent, context: Dict[str, Any]) -> Optional[Any]:
        """Execute the core business logic for the event."""
        logger.info(f"Executing main processing logic for event type '{event.type}'.")
        # FIXME: Replace with your core business logic.
        # result = await agent.process(event.data, context.get("external_data"))
        return None


def get_all_handlers() -> List[EventHandler]:
    """
    Return a list of all event handlers for the decision engine.

    FIXME: Add your custom handlers to this list.
    """
    return [ValidationHandler(), ProcessingHandler()]
