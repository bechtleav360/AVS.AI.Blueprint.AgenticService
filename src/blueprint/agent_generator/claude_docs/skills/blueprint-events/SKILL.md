---
name: blueprint-events
description: CloudEvents, the event handler chain, priorities, at-least-once delivery and idempotency, and the Dapr and NATS transports. Use when writing or debugging an EventHandler, choosing an event bus, or when events are duplicated, lost, or not reaching a handler.
user-invocable: true
---

# Event Processing

Handlers form a **chain of responsibility** ordered by priority (lower runs first). Each handler
decides whether the event is its business, and the chain stops at the first handler that returns a
result.

```bash
asbs docs concepts/event-processing --cat      # CloudEvent model, chain, transports
asbs docs components/event-handlers --cat      # writing a handler
```

## The two rules that decide behaviour

**Return value is control flow:**

- `return None` - not mine, or nothing to publish. The event passes to the next handler.
- `return HandlerResult(...)` - publish that event and **stop the chain**.

**Delivery is at-least-once.** The same event can reach `handle_event` more than once: a lost ack, a
pod restart, a rolling deploy. Either make the method safe to repeat, or set **both**
`idempotency_enabled = true` and `idempotency_ttl = <seconds>`; the framework then skips an event
whose id and source it has already dispatched, within that window. It is off by default on purpose -
only you know whether replaying your side effects is acceptable.

## Shape

```python
class OrderHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=10)          # lower runs first

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(OrderService)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "order.placed"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        order = self.extract_payload(event, OrderModel)
        result = await self._service.process(order)
        return HandlerResult(event_type="order.processed", data=result)
```

- **`self.extract_payload(event, Model)`** validates `event.data` and returns a typed instance,
  raising `InvalidEventError` that the framework handles. Do not hand-parse `event.data`.
- Handlers are a **thin delegation layer**. Business logic belongs in a service.
- Dependencies resolve in `on_startup()`, never in `__init__`.

## Publishing from elsewhere

From a REST endpoint, build the event rather than constructing it by hand:

```python
from blueprint.agents.models import create_cloud_event

cloud_event = create_cloud_event("order.created", payload, source="/api/orders")
result = await event_processing.process_event(cloud_event)
```

It generates the id, calls `model_dump()` on Pydantic models and sets the defaults.

## Transport

`event_bus` selects `"dapr"` or `"nats"`. Their sections in `concepts/event-processing` cover
subscriptions, queue groups, JetStream durables and *Broker Startup Resilience*. In a group, the
agent namespace is part of every durable name - see `blueprint-multi-agent` before renaming
anything.
