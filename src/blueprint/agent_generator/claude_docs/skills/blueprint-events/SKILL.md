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

- `return HandlerResult(...)` - publish that event and **stop the chain**.
- `return HandlerResult.skipped("reason")` - this handler is responsible but the event needs
  nothing: **stop the chain**, acknowledge, log the reason at INFO, count `blueprint.events.skipped`.
- `return None` - another handler should get it. The event passes to the next handler; if none
  takes it, the framework logs "No handler processed event".

**Delivery is at-least-once.** The same event can reach `handle_event` more than once: a lost ack, a
pod restart, a rolling deploy. Either make the service it calls safe to repeat, or set **both**
`idempotency_enabled = true` and `idempotency_ttl = <seconds>`; the framework then skips an event
whose id and source it has already dispatched, within that window. It is off by default on purpose -
only you know whether replaying your side effects is acceptable.

**The handler context tells a JetStream run which attempt it is:** `nats_delivery_attempt`
(1-based) and `nats_max_deliver` (`None` when unlimited). Equal means the last attempt: a failure is
not redelivered. Pass both to the service if it must close open work on the last attempt.

**Never swallow `asyncio.CancelledError`** in a handler or anything it calls. A run that exceeds
`nats_handler_timeout` is cancelled; code that catches the cancellation (`except BaseException`, a
bare `except:`, `except asyncio.CancelledError` without `raise`) keeps working past the limit and is
nak'd and redelivered anyway, so its work may run twice. Catch `Exception` instead, or re-raise.
`asbs validate` warns with file and line.

## Shape

```python
class OrderHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=10)          # lower runs first

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(OrderService)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "order.placed"    # envelope only: no I/O, no service call

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        payload = self.extract_payload(event, OrderPlacedEvent)
        outcome = await self._service.on_order_placed(payload.order_id, event_id=event.id)   # ONE call
        if outcome is None:
            return HandlerResult.skipped("order needs no processing")
        return HandlerResult(event_type="order.processed", data=outcome.model_dump())
```

- **`self.extract_payload(event, Model)`** validates `event.data` and returns a typed instance,
  raising `InvalidEventError` that the framework handles. Do not hand-parse `event.data`.
- **A handler translates, it never decides.** `extract_payload` -> exactly one service call with
  domain values (never the CloudEvent or the DTO) -> result. Two service calls in a row are
  business logic: give the service one entry-point method.
- **Relevance is the service's decision** ("did the status change?"); the handler reports "no" as
  `HandlerResult.skipped(reason)`.
- **No LLM in a handler**: no `agent.run()`, no `registry.get_agent()`, no runtime from `context`.
- **No run state on `self`**: runs are concurrent; per-event values stay in locals.
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
