---
description: Create a new EventHandler subclass for processing CloudEvents
---

## Steps

1. Identify the event type to handle (e.g. `order.placed`) and target directory (e.g. `src/handlers/`).

2. Create `src/handlers/order_handler.py`:

```python
"""Handler for order.placed events."""

import logging

from blueprint.agents.base import EventHandler
from blueprint.agents.models import HandlerResult
from blueprint.agents.models.events import GenericCloudEvent

from ..services import OrderService

logger = logging.getLogger(__name__)


class OrderPlacedHandler(EventHandler):
    """Processes ``order.placed`` CloudEvents.

    Priority 10 — runs before any lower-priority handlers.
    """

    def __init__(self) -> None:
        super().__init__(name="OrderPlacedHandler", priority=10)

    async def on_startup(self) -> None:
        self._service: OrderService = self.get_registry().get_service("order_service")

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict
    ) -> bool:
        return event.type == "order.placed"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict
    ) -> HandlerResult | None:
        logger.info("Processing order.placed event: %s", event.id)

        order = await self._service.create_from_event(event.data)

        return HandlerResult(
            event_type="order.confirmed",
            data=order.model_dump(),
            metadata={"handler": self.get_name(), "order_id": order.id},
        )
```

3. Export from `src/handlers/__init__.py`:

```python
from .order_handler import OrderPlacedHandler
```

4. Register in `src/main.py`:

```python
from .handlers import OrderPlacedHandler
from .services import OrderService

app = (
    AppBuilder(config=config)
    .with_service(OrderService())
    .with_handler(OrderPlacedHandler())
    .build()
)
```

## Return value reference

| Return | Effect |
|--------|--------|
| `HandlerResult(event_type="x", data={...})` | Stops chain; publishes event of type `"x"` |
| `HandlerResult(event_type=None, data={...})` | Stops chain; does NOT publish |
| `[HandlerResult(...), HandlerResult(...)]` | Stops chain; publishes each with non-None `event_type` |
| `None` | Passes to next handler in priority order |

## Rules

- Lower `priority` numbers run first (default is 100).
- `can_handle_event()` must be fast and side-effect-free — it is called for every event.
- Never raise exceptions from `handle_event()` for expected error cases — return a `HandlerResult` with an error event type instead.
- Resolve all dependencies in `on_startup()`, not in `__init__`.
