"""Example event handlers demonstrating the Chain of Responsibility pattern.

Guide: How to add a custom handler
----------------------------------

Handlers process events in priority order. Each handler can:
1. Check if it can handle the event (can_handle_event)
2. Process the event and either:
   - Return a result (stops the chain)
   - Return None (continues to next handler)
3. Optionally call agents using await self._get_agent_runtime()

Example:

```python
from base.src.handler import EventHandler
from base.src.models import CloudEvent

class MyHandler(EventHandler):
    def __init__(self):
        super().__init__("MyHandler", priority=20)

    async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
        return event.type == "my.event.type"

    async def handle_event(self, event: CloudEvent, context: dict):
        # Simple processing - no agent needed
        return {"status": "processed", "data": event.data}

        # OR call agent if needed
        runtime = await self._get_agent_runtime("my_analyzer")
        result = await runtime.process_request(context={...})
        return {"status": "success", "result": result}
```

Best practices:
- Keep handlers single-purpose and composable
- Return None to continue chain, return result to stop
- Call agents directly when needed using _get_agent_runtime()
- Use context to pass data between handlers
"""

import logging
from typing import Any

from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import HarmonizingInputPayload


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


# from ..models.domain import AgentOutput

logger = logging.getLogger(__name__)


class SimpleProcessorHandler(EventHandler):
    """Handler that performs lightweight processing without invoking the agent."""

    def __init__(self) -> None:
        super().__init__("SimpleProcessorHandler", priority=15)

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Handle events with HarmonizingInputPayload structure."""
        if not event.data or not isinstance(event.data, HarmonizingInputPayload):
            return False
        # TODO: Update this logic based on your business requirements
        # The new payload doesn't have 'details.action' field
        return True

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
