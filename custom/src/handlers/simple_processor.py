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
from typing import Any

from ..api.rest import CustomPayload


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


from base.src.handler import EventHandler
from base.src.models import CloudEvent

# from ..models.domain import AgentOutput

logger = logging.getLogger(__name__)


class SimpleProcessorHandler(EventHandler):
    """Handler that performs lightweight processing without invoking the agent."""

    def __init__(self) -> None:
        super().__init__("SimpleProcessorHandler", priority=15)

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Handle events with 'simple_process' action."""
        if not event.data or not isinstance(event.data, CustomPayload):
            return False
        return event.data.details.get("action") == "simple_process"

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        """Process the payload without agent invocation."""
        payload = event.data
        logger.info("SimpleProcessorHandler processing event '%s' without agent", event.type)

        result = {
            "status": "processed",
            "processed_by": [self.name],
            "data": {
                "invoice_id": payload.invoice_id,
                "line_item_count": len(payload.line_items),
                "currency": payload.currency,
                "enriched_at": "timestamp_placeholder",
                "details": payload.details,
            },
        }

        context["processed_without_agent"] = True

        return result

    def get_runtime_name(self, event: CloudEvent, context: dict[str, Any]) -> str | None:
        """Return None to skip agent processing for simple events."""
        return None  # No agent needed for simple processing
