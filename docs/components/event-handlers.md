# Event Handlers

Event handlers process incoming CloudEvents using a chain-of-responsibility pattern. Each handler declares which events it can process, and the framework routes events through all registered handlers in priority order.

## Import

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
```

## Purpose

Event handlers are the primary entry point for asynchronous event processing. When a CloudEvent arrives (via Dapr, NATS, or HTTP), the framework iterates through all registered handlers in priority order. Each handler is asked whether it can process the event via `can_handle_event()`; if it can, `handle_event()` is called. Handlers should be thin — delegate all domain logic to services.

## Base Class

```python
from typing import Any
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult


class MyHandler(EventHandlerBase):

    def __init__(self) -> None:
        super().__init__(priority=100)  # Lower priority runs first

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(MyService)

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> bool:
        ...

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> Any | HandlerResult | list[HandlerResult] | None:
        ...
```

## Priority

The `priority` argument controls execution order. Handlers with a **lower** numeric priority value are evaluated first. If two handlers share the same priority, ordering is non-deterministic.

```python
super().__init__(priority=10)   # Runs early
super().__init__(priority=100)  # Default
super().__init__(priority=500)  # Runs late
```

## Abstract Methods

### can_handle_event

Determines whether this handler should process the given event. Return `True` to claim the event, `False` to skip it. Even if `False` is returned, the next handler still runs — returning `False` does not stop the chain.

```python
async def can_handle_event(
    self, event: GenericCloudEvent, context: dict[str, Any]
) -> bool:
    return event.type == "order.created"
```

### handle_event

Performs the actual processing. Called only when `can_handle_event` returned `True`.

```python
async def handle_event(
    self, event: GenericCloudEvent, context: dict[str, Any]
) -> Any | HandlerResult | list[HandlerResult] | None:
    result = await self._order_service.process(event.data)
    return HandlerResult(data=result, event_type="order.processed")
```

## Return Value Semantics

The return value of `handle_event` controls what happens next:

| Return Value | Behavior |
|---|---|
| `None` | Passes control to the next handler in the chain. |
| `HandlerResult` | Publishes a new CloudEvent downstream; passes control to the next handler. |
| `list[HandlerResult]` | Publishes multiple CloudEvents; passes control to the next handler. |
| Any other value | Stored internally for chaining; no event publication; passes to next handler. |

Note: The handler chain always continues through all handlers that return `True` from `can_handle_event`. Returning a `HandlerResult` does not stop subsequent handlers.

## Sharing Data Between Handlers via context

The `context` dictionary is shared across all handlers processing the same event. A handler early in the chain (low priority) can write parsed or enriched data into `context`, and a later handler reads it — avoiding redundant work.

```python
# Handler at priority 5 -- runs first
class NormalizerHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=5)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "webhook.received"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
        # Parse once and store for downstream handlers
        normalized = self._service.normalize(event.data)
        context["normalized"] = normalized
        context["source"] = normalized.source
        return None  # Pass to next handler


# Handler at priority 20 -- runs after NormalizerHandler but double checked with filled context
class EnricherHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=20)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return context.get("normalized") and event.type == "webhook.received"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult | None:
        # Read data written by the earlier handler
        normalized = context.get("normalized")

        enriched = self._service.enrich(normalized)
        return HandlerResult(event_type="webhook.processed", data=enriched)
```

## Published Event Types

Optionally declare the event types this handler can produce. Used for documentation and subscription introspection.

```python
def get_published_event_types(self) -> tuple[str, str] | None:
    return ("order.processed", "order.error")
```

The tuple is `(success_type, error_type)`. Return `None` if the handler does not publish events.

## Accessing Services

Resolve service dependencies in `on_startup()`. Never in `__init__()`.

```python
from blueprint.agents.services.service_base import ServiceBase


class OrderService(ServiceBase):
    async def process(self, order: dict) -> dict:
        ...


class OrderHandler(EventHandlerBase):

    def __init__(self) -> None:
        super().__init__(priority=100)
        self._order_service: OrderService | None = None

    async def on_startup(self) -> None:
        self._order_service = self.registry.get_service(OrderService)

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> bool:
        return event.type == "order.created"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult | None:
        if self._order_service is None:
            return None
        result = await self._order_service.process(event.data)
        return HandlerResult(data=result, event_type="order.processed")
```

## Registration

Register handlers with `AppBuilder` by passing the **class** or an instance of the class:

```python
from blueprint.agents import AppBuilder, Config

config = Config(settings_files=["settings.toml", "secrets.toml"])
app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_handler(OrderHandler)
    .build()
)
```

Services must be registered before the handlers that depend on them.

## Full Example

```python
from typing import Any
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from blueprint.agents.services.service_base import ServiceBase


class InvoiceService(ServiceBase):
    """Domain service for invoice processing."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def generate_invoice(self, order_id: str, items: list[dict]) -> dict:
        return {"invoice_id": "INV-001", "order_id": order_id, "total": 99.99}


class InvoiceHandler(EventHandlerBase):
    """Generates invoices when an order is confirmed."""

    def __init__(self) -> None:
        super().__init__(priority=50)
        self._invoice_service: InvoiceService | None = None

    async def on_startup(self) -> None:
        self._invoice_service = self.registry.get_service(InvoiceService)

    async def on_shutdown(self) -> None:
        pass

    def get_published_event_types(self) -> tuple[str, str] | None:
        return ("invoice.created", "invoice.error")

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> bool:
        return event.type == "order.confirmed"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult | None:
        if self._invoice_service is None:
            return None

        order_data = event.data or {}
        order_id = order_data.get("order_id", "")
        items = order_data.get("items", [])

        try:
            invoice = await self._invoice_service.generate_invoice(order_id, items)
            return HandlerResult(data=invoice, event_type="invoice.created")
        except Exception as exc:
            return HandlerResult(
                data={"order_id": order_id, "error": str(exc)},
                event_type="invoice.error",
            )
```

## Testing

Use a mock registry to unit test handlers in isolation. 

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from blueprint.agents.models.events import GenericCloudEvent


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    invoice_service = AsyncMock()
    invoice_service.generate_invoice.return_value = {
        "invoice_id": "INV-TEST",
        "order_id": "ORD-1",
        "total": 50.00,
    }
    registry.get_service.return_value = invoice_service
    return registry


@pytest.fixture
async def handler(mock_registry):
    h = InvoiceHandler()
    h._registry = mock_registry
    await h.on_startup()
    return h


async def test_can_handle_matching_event(handler):
    event = GenericCloudEvent(id="1", type="order.confirmed", data={})
    assert await handler.can_handle_event(event, {}) is True


async def test_ignores_unrelated_event(handler):
    event = GenericCloudEvent(id="2", type="user.created", data={})
    assert await handler.can_handle_event(event, {}) is False


async def test_handle_event_returns_result(handler):
    event = GenericCloudEvent(
        id="3",
        type="order.confirmed",
        data={"order_id": "ORD-1", "items": [{"sku": "A", "qty": 2}]},
    )
    result = await handler.handle_event(event, {})
    assert result is not None
    assert result.event_type == "invoice.created"
    assert result.data["invoice_id"] == "INV-TEST"
```
