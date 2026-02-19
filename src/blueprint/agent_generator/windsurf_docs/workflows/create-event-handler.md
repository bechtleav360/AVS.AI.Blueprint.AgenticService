---
description: Create a new EventHandler subclass for processing CloudEvents
---

Ask the user for:
- Event type to handle (e.g. `order.placed`)
- Handler name (e.g. `OrderPlacedHandler`)
- Priority (default: 10 for first handlers, 100 for fallbacks)
- Services and agents it needs

Then follow these steps:

1. Create `src/handlers/{name}_handler.py`:

```python
"""Handler for {event_type} events."""

import logging

from blueprint.agents.base import EventHandler
from blueprint.agents.models import HandlerResult
from blueprint.agents.models.events import GenericCloudEvent

from ..services import {Service}

logger = logging.getLogger(__name__)


class {Name}Handler(EventHandler):
    """Processes ``{event_type}`` CloudEvents.

    Priority {priority} — adjust to control evaluation order (lower = earlier).
    """

    def __init__(self) -> None:
        super().__init__(name="{Name}Handler", priority={priority})

    async def on_startup(self) -> None:
        self._service: {Service} = self.get_registry().get_service("{service_name}")

    async def can_handle_event(
        self, event: GenericCloudEvent, context: dict
    ) -> bool:
        return event.type == "{event_type}"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict
    ) -> HandlerResult | None:
        logger.info("Processing {event_type} event: %s", event.id)

        result = await self._service.process(event.data)

        return HandlerResult(
            event_type="{output_event_type}",
            data=result.model_dump() if hasattr(result, "model_dump") else result,
            metadata={{"handler": self.get_name()}},
        )
```

2. Export from `src/handlers/__init__.py`:

```python
from .{name}_handler import {Name}Handler
```

3. Register in `src/main.py`:

```python
from .handlers import {Name}Handler
from .services import {Service}

app = (
    AppBuilder(config=config)
    .with_service({Service}())
    .with_handler({Name}Handler())
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

## Rules to follow

- Lower `priority` numbers run first (default is 100).
- `can_handle_event()` must be fast and side-effect-free.
- Resolve all dependencies in `on_startup()`, not in `__init__`.
