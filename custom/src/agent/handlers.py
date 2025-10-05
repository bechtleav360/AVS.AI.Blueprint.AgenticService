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


from base.src.agent import EventHandler
from base.src.models.events import CloudEvent

# from ..models.domain import AgentOutput

logger = logging.getLogger(__name__)


class AgentInvokerHandler(EventHandler):
    """Handler that validates input and invokes the Pydantic AI agent."""

    def __init__(self) -> None:
        super().__init__("AgentInvokerHandler", priority=10)

    async def _can_handle(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Handle events with 'invoke_agent' action."""
        if not event.data or not isinstance(event.data, CustomPayload):
            return False
        return event.data.details.get("action") == "invoke_agent"

    async def _handle(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        """Validate the payload and trigger the agent."""
        logger.info("AgentInvokerHandler validated event '%s' and will request agent support", event.type)

        # Pass unstructured invoice text to context for agent processing
        payload = event.data
        context["validated_at"] = "timestamp_placeholder"
        context["use_agent"] = True
        context["agent_name"] = "AgentRuntime"
        context["invoice_text"] = payload.invoice_text
        context["metadata"] = payload.details

        return None


class SimpleProcessorHandler(EventHandler):
    """Handler that performs lightweight processing without invoking the agent."""

    def __init__(self) -> None:
        super().__init__("SimpleProcessorHandler", priority=15)

    async def _can_handle(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Handle events with 'simple_process' action."""
        if not event.data or not isinstance(event.data, CustomPayload):
            return False
        return event.data.details.get("action") == "simple_process"

    async def _handle(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
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

        # Mark that agent is NOT needed
        context["use_agent"] = False
        context["processed_without_agent"] = True

        return result


class ProcessingHandler(EventHandler):
    """Example handler that performs a lightweight transformation without the agent."""

    def __init__(self) -> None:
        super().__init__("ProcessingHandler", priority=30)

    async def _can_handle(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """This handler runs after validation to enrich payloads."""
        return "validated_at" in context

    async def _handle(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        """Transform the payload and keep processing within the handler chain."""
        payload = event.data.dict() if hasattr(event.data, "dict") else event.data

        if not isinstance(payload, dict):
            logger.warning("ProcessingHandler received unsupported payload type %s", type(event.data))
            raise HandlerError(
                status="skipped",
                reason="Unsupported payload",
                code="unsupported_payload",
            )

        logger.info("ProcessingHandler enriching data for event '%s'", event.type)

        transformed_payload = {
            "original": payload,
            "metadata": {
                "invoice_id": payload.get("invoice_id") or payload.get("id"),
                "line_item_count": len(payload.get("line_items", [])),
                "currency": payload.get("currency", "EUR"),
            },
        }

        context["transformed_payload"] = transformed_payload
        context.setdefault("use_agent", False)

        return {
            "status": "processed",
            "processed_by": [self.name],
            "data": transformed_payload,
        }


# The list of all event handlers for the decision engine.
all_handlers = [AgentInvokerHandler(), SimpleProcessorHandler(), ProcessingHandler()]
