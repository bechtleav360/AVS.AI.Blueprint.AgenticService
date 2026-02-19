---
description: Create a new Scheduler subclass for background cron-based tasks
---

## Steps

1. Identify the schedule (cron expression) and target directory (e.g. `src/schedulers/`).

2. Create `src/schedulers/cleanup_scheduler.py`:

```python
"""Scheduler that runs cleanup tasks on a cron schedule."""

import logging

from blueprint.agents.base import Scheduler

from ..services import CacheService

logger = logging.getLogger(__name__)


class CleanupScheduler(Scheduler):
    """Runs cache cleanup every hour.

    Crontab: ``0 * * * *``  (top of every hour)
    """

    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *", name="CleanupScheduler")

    async def on_startup(self) -> None:
        # Resolve dependencies BEFORE calling super().on_startup()
        # super() starts the asyncio task — tick() may fire immediately
        self._cache: CacheService = self.get_registry().get_service("cache_service")
        await super().on_startup()
        logger.info("CleanupScheduler ready")

    async def tick(self) -> None:
        """Called once per cron interval."""
        logger.info("Running cleanup tick")
        await self._cache.clear_expired()
```

3. Export from `src/schedulers/__init__.py`:

```python
from .cleanup_scheduler import CleanupScheduler
```

4. Register in `src/main.py` — **register service dependencies before the scheduler**:

```python
from .schedulers import CleanupScheduler
from .services import CacheService

app = (
    AppBuilder(config=config)
    .with_service(CacheService())     # dependency first
    .with_scheduler(CleanupScheduler())
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

## Rules

- Always call `await super().on_startup()` **after** resolving dependencies — the base class starts the asyncio task there.
- `tick()` is called in an `asyncio` context — use `await` freely.
- Unhandled exceptions in `tick()` are caught and logged by the base class; the scheduler keeps running.
- Use a shared `BusinessService` to communicate data between the scheduler and REST APIs or handlers.
- The `name` passed to `super().__init__()` must be unique across all registered schedulers.
