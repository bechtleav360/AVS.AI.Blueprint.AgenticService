---
description: Create a new Scheduler subclass for background cron-based tasks
---

Ask the user for:
- Scheduler name (e.g. `CleanupScheduler`)
- Cron expression (e.g. `0 * * * *` for every hour)
- Services it depends on
- What `tick()` should do

Then follow these steps:

1. Create `src/schedulers/{name}.py`:

```python
"""{Description} scheduler."""

import logging

from blueprint.agents.base import Scheduler

from ..services import {Service}

logger = logging.getLogger(__name__)


class {Name}Scheduler(Scheduler):
    """{Description}.

    Crontab: ``{crontab}``
    """

    def __init__(self) -> None:
        super().__init__(crontab="{crontab}", name="{Name}Scheduler")

    async def on_startup(self) -> None:
        # Resolve dependencies BEFORE calling super().on_startup()
        # super() starts the asyncio task — tick() may fire immediately
        self._service: {Service} = self.get_registry().get_service("{service_name}")
        await super().on_startup()
        logger.info("{Name}Scheduler ready")

    async def tick(self) -> None:
        """Called once per cron interval."""
        logger.info("{Name}Scheduler tick")
        await self._service.do_work()
```

2. Export from `src/schedulers/__init__.py`:

```python
from .{name} import {Name}Scheduler
```

3. Register in `src/main.py` — register service dependencies **before** the scheduler:

```python
from .schedulers import {Name}Scheduler
from .services import {Service}

app = (
    AppBuilder(config=config)
    .with_service({Service}())        # dependency first
    .with_scheduler({Name}Scheduler())
    .build()
)
```

## Crontab quick reference

| Expression | Meaning |
|------------|---------|
| `* * * * *` | Every minute |
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Top of every hour |
| `0 6 * * *` | Every day at 06:00 |
| `0 6 * * 1` | Every Monday at 06:00 |
| `0 0 1 * *` | First of every month at midnight |

## Rules to follow

- Always call `await super().on_startup()` **after** resolving dependencies.
- `tick()` runs in an asyncio context — use `await` freely.
- Unhandled exceptions in `tick()` are caught and logged by the base class; the scheduler keeps running.
- Use a shared `BusinessService` to share data between the scheduler and REST APIs.
