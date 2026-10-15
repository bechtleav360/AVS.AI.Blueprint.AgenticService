# Event Handlers

Event handlers process incoming CloudEvents using a chain-of-responsibility pattern. Each handler declares which events it can process, and the framework routes events through all registered handlers in priority order.

## Import

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
```

## Purpose

Event handlers are the primary entry point for asynchronous event processing. When a CloudEvent arrives (via Dapr, NATS, or HTTP), the framework iterates through all registered handlers in priority order. Each handler is asked whether it is responsible for the event via `can_handle_event()`; if it is, `handle_event()` is called, and the first result that is not `None` ends the chain. **A handler translates, it never decides:** it routes on the envelope, extracts the payload, makes one service call and turns the answer into a result. All domain logic -- including whether a particular event needs work -- lives in services.

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

Routes the event: is this handler the one for this kind of event? Return `True` to claim it, `False` to let the next handler be asked. Decide on the envelope only -- `event.type`, `event.source`, `event.subject` and the context keys -- with no I/O and no service call. Whether *this particular* event needs work is the service's decision, reported through `handle_event` (see `HandlerResult.skipped` below).

```python
async def can_handle_event(
    self, event: GenericCloudEvent, context: dict[str, Any]
) -> bool:
    return event.type == "order.created"
```

### handle_event

Called only when `can_handle_event` returned `True`. Three steps, nothing more:

1. `self.extract_payload(event, MyEventDto)` -- the typed, validated payload.
2. **One** service call with domain values (ids, domain models -- never the CloudEvent or the DTO).
   Two service calls in a row are business logic already: give the service one entry-point method.
3. The service's answer as a result.

```python
async def handle_event(
    self, event: GenericCloudEvent, context: dict[str, Any]
) -> HandlerResult | None:
    payload = self.extract_payload(event, OrderCreatedEvent)
    outcome = await self._order_service.on_order_created(payload.order_id, event_id=event.id)
    if outcome is None:
        return HandlerResult.skipped("order needs no processing")
    return HandlerResult(event_type="order.processed", data=outcome.model_dump())
```

A handler never calls the LLM -- no `agent.run()`, no `registry.get_agent()`, and it does not run the
runtime the chain puts into `context["runtime"]`. The service resolves its agent in `on_startup()`.

## Return Value Semantics

The return value of `handle_event` controls what happens next:

| Return Value | Behavior |
|---|---|
| `None` | Passes control to the next handler in the chain. If no handler returns anything else, the framework logs "No handler processed event" and acknowledges. |
| `HandlerResult` | Publishes a new CloudEvent if its `event_type` is mapped; **the chain stops**. |
| `list[HandlerResult]` | Publishes multiple CloudEvents; **the chain stops**. |
| `HandlerResult.skipped(reason)` | This handler is responsible but the event needs nothing: **the chain stops**, nothing is published, the delivery is acknowledged, the reason is logged at INFO and counted as `blueprint.events.skipped`. The run reports `ProcessingStatus.SKIPPED`; a REST caller gets `success = true` with the reason. |
| Any other value | Returned as the run's result; no event publication; **the chain stops**. |

The first handler that returns anything other than `None` ends the chain (`handler_chain.py`, `_dispatch`). Use `None` only when another handler should be offered the event; a handler that owns the event and finds nothing to do returns `HandlerResult.skipped(reason)`.

## Sharing Data Between Handlers via context

Prefer one handler per event type with a service entry point; a chain of handlers that hand data
on through `context` is for cross-cutting steps, not for splitting one piece of domain logic.

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

### What the transport puts in `context`

Before the first handler runs, the transport that delivered the event writes what it knows about the
delivery:

| Key | Transport | Value |
|---|---|---|
| `nats_topic` | NATS | The subscription as the agent declared it, possibly a wildcard: `orders.>` |
| `nats_subject` | NATS | The subject the message was delivered on, as the agent knows it: `orders.created`. On a named connection the binding's `subject_prefix` is stripped again, so a handler sees the same subject on every connection. |
| `nats_connection` | NATS | The name of the named connection the delivery came from; absent on the default connection. An opaque name for logs and for passing on -- the framework attaches no meaning to it. |
| `nats_delivery_attempt` | NATS, JetStream | Which attempt this delivery is, 1-based (the broker's `num_delivered`): `1` the first time, `2` after one redelivery. Absent for Core NATS, which does not redeliver. |
| `nats_max_deliver` | NATS, JetStream | The attempts the delivering consumer allows -- the binding's `max_deliver` on a named connection, `nats_max_deliver` otherwise; `None` when unlimited or unknown. Present exactly when `nats_delivery_attempt` is. |
| `dapr_topic` | Dapr | The topic the sidecar delivered to |

**Derive anything security-relevant from the delivery, not from the event.** Every field of the
event is whatever the publisher wrote. The connection and the subject are what the broker routed --
under subject-scoped publish permissions, what the broker checked the publisher was allowed to use.
Nothing in the payload can overwrite a context key. Which deployment-level scope a connection stands
for is decided by the connection source (its `validate` and `run_scope` hooks), not by handlers.

**The last attempt.** When `nats_delivery_attempt == nats_max_deliver`, a failure of this run is not
redelivered -- it is dead-lettered or dropped. A service that keeps work open across attempts (a
claimed job, a pending record) can close or hand it off on that attempt instead of leaving it open.
The handler passes the two values to the service as parameters; it does not decide.

The keys are present only for events NATS delivered: a test, a direct `process_event` call or another
transport has none, so read them with `.get()` where that can happen. Handlers share `context`,
so a handler earlier in the chain could overwrite them -- do not write to transport keys.

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

Register handlers with `AppBuilder` by passing the **class** -- an instance is refused in a group,
because it would be constructed before any namespace exists. In `src/main.py` (a declaration; see
[agents](agents.md) and the `create_app()` that `asbs setup` writes):

```python
from blueprint.agents import AppBuilder

agent = (
    AppBuilder()
    .with_service(OrderService)
    .with_handler(OrderHandler)
)
```

Services must be registered before the handlers that depend on them.

## Full Example

```python
from typing import Any

from pydantic import BaseModel

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from blueprint.agents.services.service_base import ServiceBase


class OrderConfirmedEvent(BaseModel):
    """DTO: the payload of an order.confirmed event."""

    order_id: str
    items: list[dict]


class InvoiceService(ServiceBase):
    """Domain service for invoice processing."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def generate_invoice(self, order_id: str, items: list[dict]) -> dict | None:
        """None: nothing to invoice."""
        if not items:
            return None
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
        payload = self.extract_payload(event, OrderConfirmedEvent)  # DTO, validated
        invoice = await self._invoice_service.generate_invoice(payload.order_id, payload.items)
        if invoice is None:
            return HandlerResult.skipped("order has nothing to invoice")
        return HandlerResult(data=invoice, event_type="invoice.created")
```

A failure is not turned into a result here: an exception reaches the transport, which settles the
delivery (nak and redeliver, or terminate for `InvalidEventError`). If the domain needs an
`invoice.error` event, the service decides that and returns it as its answer.

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
